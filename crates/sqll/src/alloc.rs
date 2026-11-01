//! The memory allocator of the sqll binary (S3 T17).
//!
//! The parser and the lexer make and free many small blocks: in the parse
//! of a large file, malloc and free of the C library were about 30% of the
//! instructions. This allocator keeps a free list for each size class of
//! small blocks, in each thread, and takes new blocks from large chunks. A
//! small allocation or free is a few instructions, with no lock.
//!
//! - Small blocks: size at most MAX_SMALL and alignment at most GRANULE. The
//!   size class is the size rounded up to GRANULE. A free block goes to the
//!   free list of its class in the thread that frees it, and the next
//!   allocation of that class can use it. The chunks are never given back,
//!   so a block can move between threads.
//! - Other blocks: the system allocator.
//!
//! The memory of a free small block is not given back to the system before
//! the process exits; a command of sqll is one short process.

use std::alloc::{GlobalAlloc, Layout, System};
use std::cell::Cell;
use std::ptr;

const GRANULE: usize = 16;
const MAX_SMALL: usize = 1024;
const CLASSES: usize = MAX_SMALL / GRANULE;
const CHUNK: usize = 1024 * 1024;

pub struct Allocator;

struct Heap {
    /// The first free block of each class. A free block holds the pointer
    /// to the next free block of its class.
    free: [Cell<*mut u8>; CLASSES],
    /// The unused part of the current chunk: [next, end).
    next: Cell<*mut u8>,
    end: Cell<*mut u8>,
}

thread_local! {
    // A const value with no destructor: the access is a load from the
    // thread block, and it does not allocate.
    static HEAP: Heap = const {
        Heap {
            free: [const { Cell::new(ptr::null_mut()) }; CLASSES],
            next: Cell::new(ptr::null_mut()),
            end: Cell::new(ptr::null_mut()),
        }
    };
}

#[inline]
fn is_small(layout: &Layout) -> bool {
    layout.size() <= MAX_SMALL && layout.align() <= GRANULE
}

/// The class of a small size: 0 for 1 to 16 bytes (and for 0), 1 for 17 to
/// 32 bytes, and so on.
#[inline]
fn class_of(size: usize) -> usize {
    size.saturating_sub(1) / GRANULE
}

#[inline]
fn class_size(class: usize) -> usize {
    (class + 1) * GRANULE
}

impl Heap {
    #[inline]
    unsafe fn alloc(&self, class: usize) -> *mut u8 {
        let head = self.free[class].get();
        if !head.is_null() {
            self.free[class].set(unsafe { *(head as *mut *mut u8) });
            return head;
        }
        let size = class_size(class);
        let next = self.next.get();
        if (self.end.get() as usize) - (next as usize) >= size {
            self.next.set(unsafe { next.add(size) });
            return next;
        }
        unsafe { self.alloc_from_new_chunk(size) }
    }

    #[cold]
    unsafe fn alloc_from_new_chunk(&self, size: usize) -> *mut u8 {
        // The rest of the old chunk stays unused.
        let chunk = unsafe { System.alloc(Layout::from_size_align_unchecked(CHUNK, GRANULE)) };
        if chunk.is_null() {
            return chunk;
        }
        self.next.set(unsafe { chunk.add(size) });
        self.end.set(unsafe { chunk.add(CHUNK) });
        chunk
    }

    #[inline]
    unsafe fn free(&self, block: *mut u8, class: usize) {
        unsafe { *(block as *mut *mut u8) = self.free[class].get() };
        self.free[class].set(block);
    }
}

unsafe impl GlobalAlloc for Allocator {
    #[inline]
    unsafe fn alloc(&self, layout: Layout) -> *mut u8 {
        if !is_small(&layout) {
            return unsafe { System.alloc(layout) };
        }
        let class = class_of(layout.size());
        HEAP.try_with(|heap| unsafe { heap.alloc(class) })
            .unwrap_or_else(|_| unsafe {
                // No thread heap (not expected): a block of the full class
                // size, so that a later free can put it in a free list.
                System.alloc(Layout::from_size_align_unchecked(class_size(class), GRANULE))
            })
    }

    #[inline]
    unsafe fn dealloc(&self, block: *mut u8, layout: Layout) {
        if !is_small(&layout) {
            return unsafe { System.dealloc(block, layout) };
        }
        let class = class_of(layout.size());
        // With no thread heap (not expected), the block stays allocated.
        let _ = HEAP.try_with(|heap| unsafe { heap.free(block, class) });
    }

    #[inline]
    unsafe fn alloc_zeroed(&self, layout: Layout) -> *mut u8 {
        if !is_small(&layout) {
            return unsafe { System.alloc_zeroed(layout) };
        }
        let block = unsafe { self.alloc(layout) };
        if !block.is_null() {
            unsafe { ptr::write_bytes(block, 0, layout.size()) };
        }
        block
    }

    #[inline]
    unsafe fn realloc(&self, block: *mut u8, layout: Layout, new_size: usize) -> *mut u8 {
        let new_layout = unsafe { Layout::from_size_align_unchecked(new_size, layout.align()) };
        match (is_small(&layout), is_small(&new_layout)) {
            (false, false) => unsafe { System.realloc(block, layout, new_size) },
            (true, true) if class_of(layout.size()) == class_of(new_size) => block,
            _ => {
                let new_block = unsafe { self.alloc(new_layout) };
                if !new_block.is_null() {
                    let n = layout.size().min(new_size);
                    unsafe {
                        ptr::copy_nonoverlapping(block, new_block, n);
                        self.dealloc(block, layout);
                    }
                }
                new_block
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_classes_cover_each_small_size() {
        assert_eq!(class_of(0), 0);
        assert_eq!(class_of(1), 0);
        assert_eq!(class_of(16), 0);
        assert_eq!(class_of(17), 1);
        assert_eq!(class_of(MAX_SMALL), CLASSES - 1);
        for size in 0..=MAX_SMALL {
            assert!(class_size(class_of(size)) >= size);
        }
    }

    #[test]
    fn a_freed_block_is_used_again_for_its_class() {
        let a = Allocator;
        let layout = Layout::from_size_align(40, 8).unwrap();
        unsafe {
            let p = a.alloc(layout);
            assert_eq!(p as usize % GRANULE, 0);
            a.dealloc(p, layout);
            let q = a.alloc(Layout::from_size_align(48, 16).unwrap());
            assert_eq!(p, q);
            a.dealloc(q, Layout::from_size_align(48, 16).unwrap());
        }
    }

    #[test]
    fn blocks_do_not_overlap_and_keep_their_data() {
        let a = Allocator;
        let mut blocks = Vec::new();
        for i in 0..20_000usize {
            let size = 1 + (i * 37) % 1500;
            let layout = Layout::from_size_align(size, if i % 3 == 0 { 16 } else { 8 }).unwrap();
            let p = unsafe { a.alloc(layout) };
            assert!(!p.is_null());
            unsafe { ptr::write_bytes(p, (i % 251) as u8, size) };
            blocks.push((p, layout, (i % 251) as u8));
            if i % 5 == 0 {
                let (p, layout, _) = blocks.swap_remove(i % blocks.len());
                unsafe { a.dealloc(p, layout) };
            }
        }
        for (p, layout, byte) in &blocks {
            let data = unsafe { std::slice::from_raw_parts(*p, layout.size()) };
            assert!(data.iter().all(|b| b == byte));
        }
        for (p, layout, _) in blocks {
            unsafe { a.dealloc(p, layout) };
        }
    }

    #[test]
    fn realloc_keeps_the_data_across_classes_and_sizes() {
        let a = Allocator;
        let mut layout = Layout::from_size_align(8, 8).unwrap();
        let mut p = unsafe { a.alloc(layout) };
        unsafe { ptr::write_bytes(p, 7, 8) };
        for new_size in [12, 40, 600, 1024, 5000, 70_000, 900, 3] {
            p = unsafe { a.realloc(p, layout, new_size) };
            assert!(!p.is_null());
            let keep = layout.size().min(new_size).min(8);
            let data = unsafe { std::slice::from_raw_parts(p, keep) };
            assert!(data.iter().all(|&b| b == 7));
            layout = Layout::from_size_align(new_size, 8).unwrap();
        }
        unsafe { a.dealloc(p, layout) };
    }

    #[test]
    fn a_large_or_strongly_aligned_block_comes_from_the_system() {
        assert!(!is_small(&Layout::from_size_align(MAX_SMALL + 1, 8).unwrap()));
        assert!(!is_small(&Layout::from_size_align(64, 32).unwrap()));
        let a = Allocator;
        let layout = Layout::from_size_align(64, 64).unwrap();
        let p = unsafe { a.alloc_zeroed(layout) };
        assert_eq!(p as usize % 64, 0);
        assert!(unsafe { std::slice::from_raw_parts(p, 64) }.iter().all(|&b| b == 0));
        unsafe { a.dealloc(p, layout) };
    }
}
