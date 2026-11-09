//! The catalog: the tables and their columns. S8 reads it from DDL files.

use crate::description::{Nullability, SqlType};

/// A column of a table.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct CatalogColumn {
    pub name: String,
    pub ty: SqlType,
    pub nullability: Nullability,
}

/// A table (or a view) and its columns, in order.
#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Table {
    /// The schema name, if the DDL gives one.
    pub schema: Option<String>,
    pub name: String,
    pub columns: Vec<CatalogColumn>,
}

impl Table {
    /// The column with the name (an exact compare).
    pub fn column(&self, name: &str) -> Option<&CatalogColumn> {
        self.columns.iter().find(|c| c.name == name)
    }
}

/// The tables of the DDL files. The names are as the database keeps them:
/// the reader of the DDL applies the case rules of the dialect, and a
/// lookup compares exactly.
#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Catalog {
    pub tables: Vec<Table>,
}

impl Catalog {
    /// An empty catalog.
    pub fn new() -> Catalog {
        Catalog::default()
    }

    /// The table with the schema and the name (an exact compare). With no
    /// schema, the first table with the name.
    pub fn table(&self, schema: Option<&str>, name: &str) -> Option<&Table> {
        self.tables
            .iter()
            .find(|t| t.name == name && (schema.is_none() || t.schema.as_deref() == schema))
    }
}
