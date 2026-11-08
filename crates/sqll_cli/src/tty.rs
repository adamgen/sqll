//! The terminal: is stdout a terminal, and the read of one key for
//! `fix --check` (click `getchar` and `raw_terminal` of click 8.4.2, the
//! version that sqlfluff 4.4.0 uses in the tool venv).

use std::fs::File;
use std::os::fd::AsRawFd;

/// True if stdout is a terminal.
pub fn stdout_is_terminal() -> bool {
    // SAFETY: isatty only reads the file descriptor.
    unsafe { libc::isatty(libc::STDOUT_FILENO) == 1 }
}

/// What the user typed.
pub enum Key {
    Text(String),
    /// Ctrl-C or Ctrl-D: click stops with "Aborted!" and exit code 1.
    Abort,
}

/// Read one key press as click `getchar`: from stdin if it is a terminal,
/// else from `/dev/tty`, in raw mode (up to 32 bytes).
pub fn getchar() -> std::io::Result<Key> {
    // SAFETY: isatty only reads the file descriptor.
    let stdin_tty = unsafe { libc::isatty(libc::STDIN_FILENO) == 1 };
    let tty = if stdin_tty {
        None
    } else {
        Some(File::open("/dev/tty")?)
    };
    let fd = tty.as_ref().map_or(libc::STDIN_FILENO, |f| f.as_raw_fd());
    // SAFETY: termios is plain data; tcgetattr fills it or fails.
    let mut old: libc::termios = unsafe { std::mem::zeroed() };
    if unsafe { libc::tcgetattr(fd, &mut old) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let mut raw = old;
    // SAFETY: cfmakeraw changes the flags of the struct only.
    unsafe { libc::cfmakeraw(&mut raw) };
    if unsafe { libc::tcsetattr(fd, libc::TCSAFLUSH, &raw) } != 0 {
        return Err(std::io::Error::last_os_error());
    }
    let mut buf = [0u8; 32];
    // SAFETY: the buffer has 32 bytes.
    let n = unsafe { libc::read(fd, buf.as_mut_ptr().cast(), buf.len()) };
    let error = std::io::Error::last_os_error();
    // SAFETY: the old settings come from tcgetattr.
    unsafe { libc::tcsetattr(fd, libc::TCSADRAIN, &old) };
    let n = usize::try_from(n).map_err(|_| error)?;
    let text = String::from_utf8_lossy(&buf[..n]).into_owned();
    if text == "\u{3}" || text == "\u{4}" {
        return Ok(Key::Abort);
    }
    Ok(Key::Text(text))
}
