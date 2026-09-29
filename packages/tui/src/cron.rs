//! Human-readable rendering of the simple cron shapes flows use.

const DAYS: [&str; 7] = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

/// "0 9 * * *" → "09:00", "0 9 * * 1" → "Mon 09:00", otherwise the raw expression.
pub fn describe(expr: &str) -> String {
    let f: Vec<&str> = expr.split_whitespace().collect();
    if f.len() != 5 {
        return expr.to_string();
    }
    let (Ok(min), Ok(hour)) = (f[0].parse::<u32>(), f[1].parse::<u32>()) else {
        return expr.to_string();
    };
    if min > 59 || hour > 23 || f[2] != "*" || f[3] != "*" {
        return expr.to_string();
    }
    let time = format!("{hour:02}:{min:02}");
    match f[4] {
        "*" => time,
        "1-5" => format!("Mon-Fri {time}"),
        d => match d.parse::<usize>() {
            Ok(n) if n <= 7 => format!("{} {time}", DAYS[n % 7]),
            _ => expr.to_string(),
        },
    }
}

#[cfg(test)]
mod tests {
    use super::describe;

    #[test]
    fn common_shapes() {
        assert_eq!(describe("0 9 * * *"), "09:00");
        assert_eq!(describe("30 8 * * 1"), "Mon 08:30");
        assert_eq!(describe("0 9 * * 1-5"), "Mon-Fri 09:00");
        assert_eq!(describe("*/5 * * * *"), "*/5 * * * *");
    }
}
