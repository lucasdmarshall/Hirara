//! A bounded adapter to a Rust CAS, not an executable language.
use crate::text;
use serde_json::{Value, json};
use std::collections::HashMap;
use tpt_math_symbolic::{Expr, Expr64, Symbolic, parse_expr};

fn check(expr: &Expr64, depth: usize, power: usize, nodes: &mut usize) -> Result<(), String> {
    *nodes += 1;
    if *nodes > 1024 || depth > 32 {
        return Err("expression exceeds math complexity limit".into());
    }
    match expr {
        Expr::Const(n) if !n.is_finite() => return Err("non-finite math constant".into()),
        Expr::Add(a, b) | Expr::Sub(a, b) | Expr::Mul(a, b) | Expr::Div(a, b) => {
            check(a, depth + 1, power, nodes)?;
            check(b, depth + 1, power, nodes)?;
        }
        Expr::Neg(a) | Expr::Func(_, a) => check(a, depth + 1, power, nodes)?,
        Expr::Pow(a, n) => {
            let power = power
                .checked_mul((*n).max(1))
                .filter(|p| *p <= 256)
                .ok_or("nested exponents exceed math limit")?;
            if *n > 32 {
                return Err("exponents must be between 0 and 32".into());
            }
            check(a, depth + 1, power, nodes)?;
        }
        _ => {}
    }
    Ok(())
}

fn parse(input: &str) -> Result<Expr64, String> {
    if input.is_empty() || input.len() > 1024 || !input.is_ascii() {
        return Err("expression must contain 1..1024 ASCII bytes".into());
    }
    // Bound parser recursion before constructing an AST, including unary chains.
    if input
        .bytes()
        .filter(|b| !b.is_ascii_alphanumeric() && !b.is_ascii_whitespace() && *b != b'_')
        .count()
        > 128
    {
        return Err("expression has too many operators".into());
    }
    let expr = parse_expr::<f64>(input).map_err(|e| format!("invalid math expression: {e}"))?;
    check(&expr, 0, 1, &mut 0)?;
    Ok(expr)
}

fn variable(name: &str) -> bool {
    !name.is_empty()
        && name.len() <= 32
        && name
            .bytes()
            .enumerate()
            .all(|(i, b)| b.is_ascii_alphabetic() || b == b'_' || (i > 0 && b.is_ascii_digit()))
        && !matches!(name, "pi" | "e")
}

fn multiply(a: [f64; 3], b: [f64; 3]) -> Result<[f64; 3], String> {
    let mut c = [0.0; 3];
    for i in 0..3 {
        for j in 0..3 {
            let n = a[i] * b[j];
            if i + j > 2 && n != 0.0 {
                return Err("solve supports linear and quadratic polynomials only".into());
            }
            if i + j <= 2 {
                c[i + j] += n;
            }
        }
    }
    Ok(c)
}

fn polynomial(expr: &Expr64, var: &str) -> Result<[f64; 3], String> {
    match expr {
        Expr::Const(c) => Ok([*c, 0.0, 0.0]),
        Expr::Var(name) if name == var => Ok([0.0, 1.0, 0.0]),
        Expr::Add(a, b) | Expr::Sub(a, b) => {
            let a = polynomial(a, var)?;
            let mut b = polynomial(b, var)?;
            if matches!(expr, Expr::Sub(..)) {
                for n in &mut b {
                    *n = -*n;
                }
            }
            Ok([a[0] + b[0], a[1] + b[1], a[2] + b[2]])
        }
        Expr::Mul(a, b) => multiply(polynomial(a, var)?, polynomial(b, var)?),
        Expr::Neg(a) => Ok(polynomial(a, var)?.map(|n| -n)),
        Expr::Div(a, b) => {
            let b = polynomial(b, var)?;
            if b[1] != 0.0 || b[2] != 0.0 || b[0] == 0.0 {
                return Err("solve requires constant, nonzero denominators".into());
            }
            Ok(polynomial(a, var)?.map(|n| n / b[0]))
        }
        Expr::Pow(a, n) => {
            let base = polynomial(a, var)?;
            let mut out = [1.0, 0.0, 0.0];
            for _ in 0..*n {
                out = multiply(out, base)?;
            }
            Ok(out)
        }
        _ => Err("solve supports one-variable linear and quadratic polynomials only".into()),
    }
}

pub fn run(v: &Value) -> Result<Value, String> {
    let operation = text(v, "operation")?;
    let input = text(v, "expression")?;
    if input.len() > 1024 {
        return Err("expression exceeds 1024 bytes".into());
    }
    let var = v.get("variable").and_then(Value::as_str).unwrap_or("x");
    if !variable(var) {
        return Err("invalid variable name".into());
    }
    let mut expr = if operation == "solve" {
        let parts: Vec<_> = input.split('=').collect();
        match parts.as_slice() {
            [a] => parse(a)?,
            [a, b] => parse(a)? - parse(b)?,
            _ => return Err("solve accepts at most one = sign".into()),
        }
    } else {
        parse(input)?
    };
    let mut out = json!({"operation":operation,"precision":"f64","error":null});
    match operation {
        "simplify" => expr = expr.simplify(),
        "differentiate" => {
            let order = v.get("order").and_then(Value::as_u64).unwrap_or(1);
            if !(1..=3).contains(&order) {
                return Err("derivative order must be 1..3".into());
            }
            for _ in 0..order {
                expr = expr.derivative(var);
                check(&expr, 0, 1, &mut 0)?;
                expr = expr.simplify();
            }
        }
        "evaluate" => {
            let mut env = HashMap::new();
            if let Some(vars) = v.get("variables").filter(|x| !x.is_null()) {
                let vars = vars
                    .as_object()
                    .ok_or("variables must be an object of finite numbers")?;
                if vars.len() > 32 {
                    return Err("at most 32 variable bindings are allowed".into());
                }
                for (key, value) in vars {
                    if !variable(key) {
                        return Err("invalid variable binding name".into());
                    }
                    env.insert(
                        key.clone(),
                        value
                            .as_f64()
                            .filter(|n| n.is_finite())
                            .ok_or("variable values must be finite numbers")?,
                    );
                }
            }
            out["value"] = json!(
                expr.eval(&env)
                    .filter(|n| n.is_finite())
                    .ok_or("undefined expression, missing variable or non-finite result")?
            );
        }
        "solve" => {
            expr = expr.simplify();
            let [c, b, a] = polynomial(&expr, var)?;
            if ![c, b, a].iter().all(|n| n.is_finite()) {
                return Err("non-finite polynomial coefficients".into());
            }
            let mut roots = Vec::new();
            let mut all = false;
            if a == 0.0 {
                if b != 0.0 {
                    roots.push(-c / b);
                } else {
                    all = c == 0.0;
                }
            } else {
                let discriminant = b * b - 4.0 * a * c;
                if !discriminant.is_finite() {
                    return Err("polynomial exceeds f64 numeric range".into());
                }
                if discriminant == 0.0 {
                    roots.push(-b / (2.0 * a));
                } else if discriminant > 0.0 {
                    let q = -0.5
                        * (b + if b >= 0.0 {
                            discriminant.sqrt()
                        } else {
                            -discriminant.sqrt()
                        });
                    roots.extend([q / a, c / q]);
                    roots.sort_by(f64::total_cmp);
                }
            }
            if !roots.iter().all(|n| n.is_finite()) {
                return Err("solution exceeds f64 numeric range".into());
            }
            out["solutions"] = json!(roots);
            out["all_real_in_domain"] = json!(all);
            out["domain"] = json!("real");
        }
        _ => return Err("operation must be simplify, differentiate, evaluate or solve".into()),
    }
    check(&expr, 0, 1, &mut 0)?;
    let result = expr.to_string();
    let latex = expr.to_latex();
    if result.len() + latex.len() > 64_000 {
        return Err("math result exceeds 64 KB".into());
    }
    out["result"] = json!(result);
    out["latex"] = json!(latex);
    Ok(out)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn calculus_and_equations() {
        let d = run(&json!({"operation":"differentiate","expression":"x^3 + sin(x)"})).unwrap();
        let e = run(&json!({"operation":"evaluate","expression":d["result"],"variables":{"x":2}}))
            .unwrap();
        assert!((e["value"].as_f64().unwrap() - (12.0 + 2.0f64.cos())).abs() < 1e-9);
        assert_eq!(
            run(&json!({"operation":"solve","expression":"x^2 - 5*x + 6 = 0"})).unwrap()["solutions"],
            json!([2.0, 3.0])
        );
        assert!(run(&json!({"operation":"evaluate","expression":"1/0"})).is_err());
        assert!(run(&json!({"operation":"evaluate","expression":"sqrt(-1)"})).is_err());
        assert!(run(&json!({"operation":"solve","expression":"x^3 = 1"})).is_err());
        assert!(run(&json!({"operation":"simplify","expression":"(x^32)^32"})).is_err());
    }
}
