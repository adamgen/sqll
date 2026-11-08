//! Python `repr()` of a float (the shortest text that gives the float
//! again): `json.dumps` and PyYAML write a float so.

/// Python `repr(x)` of a finite float: the shortest digits; the exponent
/// form if the decimal exponent is below -4 or at least 16 (with a sign and
/// at least 2 digits); else the fixed form with at least one digit after
/// the point.
pub fn float_repr(x: f64) -> String {
    if x.is_nan() {
        return "NaN".to_string();
    }
    if x.is_infinite() {
        return if x > 0.0 { "Infinity" } else { "-Infinity" }.to_string();
    }
    // Rust `{:e}` gives the shortest digits: "-1.2345e-5", "0e0".
    let sci = format!("{x:e}");
    let (mantissa, exp) = sci.split_once('e').expect("an exponent");
    let exp: i32 = exp.parse().expect("an integer exponent");
    let (sign, mantissa) = match mantissa.strip_prefix('-') {
        Some(m) => ("-", m),
        None => ("", mantissa),
    };
    let digits: String = mantissa.chars().filter(|c| *c != '.').collect();
    if !(-4..16).contains(&exp) {
        let (first, rest) = digits.split_at(1);
        let frac = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        let esign = if exp < 0 { '-' } else { '+' };
        return format!("{sign}{first}{frac}e{esign}{:02}", exp.abs());
    }
    let point = exp + 1;
    let n = digits.len() as i32;
    let text = if point <= 0 {
        format!("0.{}{digits}", "0".repeat((-point) as usize))
    } else if point >= n {
        format!("{digits}{}.0", "0".repeat((point - n) as usize))
    } else {
        let (a, b) = digits.split_at(point as usize);
        format!("{a}.{b}")
    };
    format!("{sign}{text}")
}

#[cfg(test)]
mod tests {
    use super::float_repr;

    #[test]
    fn float_repr_is_that_of_python() {
        // The values of Python 3.13 repr().
        for (x, want) in [
            (0.0, "0.0"),
            (-0.0, "-0.0"),
            (1.0, "1.0"),
            (0.5, "0.5"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (1.6461999621242285e-05, "1.6461999621242285e-05"),
            (0.0003141409979434684, "0.0003141409979434684"),
            (123456.789, "123456.789"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (1.5e300, "1.5e+300"),
            (12.0, "12.0"),
        ] {
            assert_eq!(float_repr(x), want, "{x}");
        }
    }
}
