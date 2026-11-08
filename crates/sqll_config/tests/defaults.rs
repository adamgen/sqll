//! The defaults of sqll_config are those of the pinned sqlfluff: the test
//! reads src/sqlfluff/core/default_config.cfg of the submodule
//! (third_party/sqlfluff, tag 4.4.0) at test time.

use std::path::Path;

use sqll_config::defaults::DEFAULTS;
use sqll_config::ini::{ini_records, load_ini_string};
use sqll_config::{defaults, Value};

fn pinned_default_config() -> String {
    let path = Path::new(env!("CARGO_MANIFEST_DIR"))
        .join("../../third_party/sqlfluff/src/sqlfluff/core/default_config.cfg");
    std::fs::read_to_string(&path).expect("read default_config.cfg of the sqlfluff submodule")
}

#[test]
fn the_defaults_are_those_of_the_pinned_sqlfluff() {
    let text = pinned_default_config();
    let records = ini_records(&text, "default_config.cfg").expect("the default config reads");
    let ours: Vec<(Vec<String>, Value)> = DEFAULTS
        .iter()
        .map(|(path, d)| (path.iter().map(|s| s.to_string()).collect(), d.value()))
        .collect();
    assert_eq!(records.len(), ours.len());
    for (want, got) in records.iter().zip(&ours) {
        assert_eq!(want, got, "the default of {}", want.0.join(":"));
    }
    assert_eq!(
        load_ini_string(&text, "default_config.cfg").expect("a table"),
        defaults()
    );
    assert_eq!(ours.len(), 208);
}
