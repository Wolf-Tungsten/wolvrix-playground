#!/usr/bin/env python3
"""Regress the NO0190 runtime cost model from collected xs-components TSVs.

This script intentionally uses only the Python standard library so it can run
in the repository's lightweight environments.
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
from pathlib import Path
from typing import Iterable


MAIN_TERMS = ["comp", "src", "sink", "succ", "exam"]
CONST_TERMS = ["comp", "src", "sink", "const", "succ", "exam"]


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def write_tsv(path: Path, rows: list[dict[str, object]], fieldnames: list[str]) -> None:
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, delimiter="\t", fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def invert_matrix(matrix: list[list[float]]) -> list[list[float]]:
    n = len(matrix)
    aug = [
        [float(matrix[i][j]) for j in range(n)]
        + [1.0 if i == j else 0.0 for j in range(n)]
        for i in range(n)
    ]
    for col in range(n):
        pivot = max(range(col, n), key=lambda row: abs(aug[row][col]))
        if abs(aug[pivot][col]) < 1e-24:
            raise ValueError("singular matrix")
        aug[col], aug[pivot] = aug[pivot], aug[col]
        pivot_value = aug[col][col]
        for j in range(2 * n):
            aug[col][j] /= pivot_value
        for row in range(n):
            if row == col:
                continue
            factor = aug[row][col]
            if factor == 0.0:
                continue
            for j in range(2 * n):
                aug[row][j] -= factor * aug[col][j]
    return [row[n:] for row in aug]


def ols(
    x: list[list[float]], y: list[float], *, centered_r2: bool = True
) -> dict[str, object]:
    n = len(y)
    p = len(x[0])
    xtx = [
        [sum(x[i][a] * x[i][b] for i in range(n)) for b in range(p)]
        for a in range(p)
    ]
    xty = [sum(x[i][a] * y[i] for i in range(n)) for a in range(p)]
    xtx_inv = invert_matrix(xtx)
    beta = [sum(xtx_inv[a][b] * xty[b] for b in range(p)) for a in range(p)]
    pred = [sum(x[i][j] * beta[j] for j in range(p)) for i in range(n)]
    resid = [y[i] - pred[i] for i in range(n)]
    rss = sum(value * value for value in resid)
    if centered_r2:
        mean_y = sum(y) / n
        tss = sum((value - mean_y) ** 2 for value in y)
    else:
        tss = sum(value * value for value in y)
    r2 = 1.0 - rss / tss if tss else float("nan")
    adj_r2 = 1.0 - (1.0 - r2) * (n - 1) / (n - p) if n > p else float("nan")
    sigma2 = rss / (n - p) if n > p else float("nan")
    se = [math.sqrt(max(0.0, sigma2 * xtx_inv[j][j])) for j in range(p)]
    return {
        "beta": beta,
        "se": se,
        "pred": pred,
        "resid": resid,
        "rss": rss,
        "r2": r2,
        "adj_r2": adj_r2,
        "rmse": math.sqrt(rss / n),
        "mae": sum(abs(value) for value in resid) / n,
        "mape_percent": mean_absolute_percent_error(y, resid),
        "n": n,
        "p": p,
        "xtx": xtx,
        "xtx_inv": xtx_inv,
    }


def jacobi_eigenvalues_symmetric(
    matrix: list[list[float]], *, max_iter: int = 10000, eps: float = 1e-12
) -> list[float]:
    n = len(matrix)
    a = [row[:] for row in matrix]
    if n == 1:
        return [a[0][0]]
    for _ in range(max_iter):
        p, q = 0, 1
        max_offdiag = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                value = abs(a[i][j])
                if value > max_offdiag:
                    max_offdiag = value
                    p, q = i, j
        if max_offdiag < eps:
            break
        if a[p][p] == a[q][q]:
            angle = math.pi / 4.0
        else:
            angle = 0.5 * math.atan2(2.0 * a[p][q], a[q][q] - a[p][p])
        c = math.cos(angle)
        s = math.sin(angle)
        app = c * c * a[p][p] - 2.0 * s * c * a[p][q] + s * s * a[q][q]
        aqq = s * s * a[p][p] + 2.0 * s * c * a[p][q] + c * c * a[q][q]
        for k in range(n):
            if k == p or k == q:
                continue
            akp = a[k][p]
            akq = a[k][q]
            a[k][p] = a[p][k] = c * akp - s * akq
            a[k][q] = a[q][k] = s * akp + c * akq
        a[p][p] = app
        a[q][q] = aqq
        a[p][q] = a[q][p] = 0.0
    return sorted(a[i][i] for i in range(n))


def mean_absolute_percent_error(y: list[float], resid: list[float]) -> float:
    valid = [index for index, value in enumerate(y) if value != 0.0]
    if not valid:
        return float("nan")
    return sum(abs(resid[index]) / y[index] for index in valid) / len(valid) * 100.0


def condition_number(x: list[list[float]]) -> float:
    p = len(x[0])
    xtx = [
        [sum(row[i] * row[j] for row in x) for j in range(p)]
        for i in range(p)
    ]
    values = jacobi_eigenvalues_symmetric(xtx)
    if not values or values[0] <= 0.0:
        return float("inf")
    return math.sqrt(values[-1] / values[0])


def pearson_corr(x: list[list[float]]) -> list[list[float]]:
    n = len(x)
    p = len(x[0])
    columns = [[x[i][j] for i in range(n)] for j in range(p)]
    out: list[list[float]] = []
    for a in range(p):
        mean_a = sum(columns[a]) / n
        var_a = sum((value - mean_a) ** 2 for value in columns[a])
        row: list[float] = []
        for b in range(p):
            mean_b = sum(columns[b]) / n
            var_b = sum((value - mean_b) ** 2 for value in columns[b])
            cov = sum(
                (columns[a][i] - mean_a) * (columns[b][i] - mean_b)
                for i in range(n)
            )
            if var_a == 0.0 or var_b == 0.0:
                row.append(float("nan"))
            else:
                row.append(cov / math.sqrt(var_a * var_b))
        out.append(row)
    return out


def variance_inflation_factors(x: list[list[float]]) -> list[float]:
    n = len(x)
    p = len(x[0])
    out: list[float] = []
    for target in range(p):
        y = [row[target] for row in x]
        z = [
            [1.0] + [row[col] for col in range(p) if col != target]
            for row in x
        ]
        fit = ols(z, y, centered_r2=True)
        r2 = float(fit["r2"])
        if not math.isfinite(r2) or r2 >= 1.0:
            out.append(float("inf"))
        else:
            out.append(1.0 / max(1e-15, 1.0 - r2))
    return out


def loocv(x: list[list[float]], y: list[float]) -> dict[str, float]:
    pred: list[float] = []
    for held_out in range(len(y)):
        train_x = [row for index, row in enumerate(x) if index != held_out]
        train_y = [value for index, value in enumerate(y) if index != held_out]
        try:
            fit = ols(train_x, train_y)
            beta = fit["beta"]
            pred.append(sum(x[held_out][j] * beta[j] for j in range(len(beta))))
        except ValueError:
            pred.append(float("nan"))
    valid = [index for index, value in enumerate(pred) if math.isfinite(value)]
    rss = sum((y[index] - pred[index]) ** 2 for index in valid)
    mean_y = sum(y) / len(y)
    tss = sum((value - mean_y) ** 2 for value in y)
    return {
        "r2": 1.0 - rss / tss,
        "rmse": math.sqrt(rss / len(valid)),
        "mae": sum(abs(y[index] - pred[index]) for index in valid) / len(valid),
        "mape_percent": (
            sum(abs(y[index] - pred[index]) / y[index] for index in valid)
            / len(valid)
            * 100.0
        ),
    }


def scaled_design(feature_rows: list[dict[str, object]], terms: list[str]) -> list[list[float]]:
    x: list[list[float]] = []
    for row in feature_rows:
        design_row: list[float] = []
        for term in terms:
            value = float(row[term])
            if term != "exam":
                value /= 1e8
            design_row.append(value)
        x.append(design_row)
    return x


def load_features(raw_dir: Path, sim: str, *, pass_only: bool = False) -> list[dict[str, object]]:
    timing_rows = read_tsv(raw_dir / "timings.tsv")
    out: list[dict[str, object]] = []
    for timing in timing_rows:
        if pass_only and timing["verify_status"] != "pass":
            continue
        static_rows = read_tsv(Path(timing[f"{sim}_static_tsv"]))
        fire_rows = read_tsv(Path(timing[f"{sim}_fire_tsv"]))
        key_names = ["supernode_id"] if sim == "gsim" else ["supernode_id", "phase"]
        fire_by_key = {
            tuple(row[name] for name in key_names): int(row["f"]) for row in fire_rows
        }
        static_keys = {tuple(row[name] for name in key_names) for row in static_rows}
        if static_keys != set(fire_by_key):
            missing_fire = len(static_keys - set(fire_by_key))
            missing_static = len(set(fire_by_key) - static_keys)
            raise ValueError(
                f"{sim} join mismatch for {timing['case']}: "
                f"missing_fire={missing_fire} missing_static={missing_static}"
            )
        sums = {"comp": 0, "src": 0, "sink": 0, "const": 0, "succ": 0}
        for static in static_rows:
            key = tuple(static[name] for name in key_names)
            fire = fire_by_key[key]
            sums["comp"] += fire * int(static["n_comp"])
            sums["src"] += fire * int(static["n_src"])
            sums["sink"] += fire * int(static["n_sink"])
            sums["const"] += fire * int(static["n_const"])
            sums["succ"] += fire * int(static["a_succ"])
        out.append(
            {
                "case": timing["case"],
                "sim": sim,
                "verify_status": timing["verify_status"],
                "ms": float(timing[f"{sim}_ms"]),
                "comp": sums["comp"],
                "src": sums["src"],
                "sink": sums["sink"],
                "const": sums["const"],
                "succ": sums["succ"],
                "exam": len(static_rows),
                "distinct_supernodes": len({row["supernode_id"] for row in static_rows}),
            }
        )
    return out


def coefficient_rows(
    sim: str, model: str, terms: list[str], fit: dict[str, object]
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    beta = fit["beta"]
    se = fit["se"]
    tcrit = 1.985
    for term, coef, stderr in zip(terms, beta, se):
        coef = float(coef)
        stderr = float(stderr)
        if term == "exam":
            unit = "ms/supernode"
            display_value = coef * 1000.0
            display_unit = "us/supernode"
        else:
            unit = "ms/1e8_ops"
            display_value = coef * 10.0
            display_unit = "ps/op"
        rows.append(
            {
                "sim": sim,
                "model": model,
                "term": term,
                "coef_scaled": coef,
                "se_scaled": stderr,
                "t": coef / stderr if stderr else float("inf"),
                "ci95_low_scaled": coef - tcrit * stderr,
                "ci95_high_scaled": coef + tcrit * stderr,
                "unit": unit,
                "coef_display": display_value,
                "display_unit": display_unit,
            }
        )
    return rows


def residual_rows(
    sim: str,
    model: str,
    features: list[dict[str, object]],
    fit: dict[str, object],
) -> list[dict[str, object]]:
    pred = fit["pred"]
    resid = fit["resid"]
    rows = []
    for index, row in enumerate(features):
        rows.append(
            {
                "sim": sim,
                "model": model,
                "case": row["case"],
                "verify_status": row["verify_status"],
                "actual_ms": row["ms"],
                "pred_ms": pred[index],
                "resid_ms": resid[index],
                "abs_resid_ms": abs(resid[index]),
            }
        )
    return sorted(rows, key=lambda row: row["abs_resid_ms"], reverse=True)


def fit_model(
    features: list[dict[str, object]], terms: list[str]
) -> tuple[list[list[float]], list[float], dict[str, object]]:
    x = scaled_design(features, terms)
    y = [float(row["ms"]) for row in features]
    return x, y, ols(x, y)


def best_nonnegative_subset(
    features: list[dict[str, object]], terms: list[str]
) -> dict[str, object]:
    y = [float(row["ms"]) for row in features]
    best: dict[str, object] | None = None
    for width in range(1, len(terms) + 1):
        for indices in itertools.combinations(range(len(terms)), width):
            subset_terms = [terms[index] for index in indices]
            x = scaled_design(features, subset_terms)
            try:
                fit = ols(x, y)
            except ValueError:
                continue
            if any(float(value) < -1e-12 for value in fit["beta"]):
                continue
            if best is None or float(fit["rss"]) < float(best["rss"]):
                full_beta = {term: 0.0 for term in terms}
                for term, coef in zip(subset_terms, fit["beta"]):
                    full_beta[term] = float(coef)
                best = {
                    "terms": subset_terms,
                    "beta": full_beta,
                    "rss": fit["rss"],
                    "r2": fit["r2"],
                    "rmse": fit["rmse"],
                    "mae": fit["mae"],
                    "mape_percent": fit["mape_percent"],
                }
    if best is None:
        raise ValueError("no nonnegative subset fit found")
    return best


def summarize_fit(
    sim: str,
    model: str,
    terms: list[str],
    x: list[list[float]],
    y: list[float],
    fit: dict[str, object],
) -> dict[str, object]:
    return {
        "sim": sim,
        "model": model,
        "terms": terms,
        "n": fit["n"],
        "p": fit["p"],
        "r2": fit["r2"],
        "adj_r2": fit["adj_r2"],
        "rmse_ms": fit["rmse"],
        "mae_ms": fit["mae"],
        "mape_percent": fit["mape_percent"],
        "loocv": loocv(x, y),
        "condition_number": condition_number(x),
        "vif": dict(zip(terms, variance_inflation_factors(x))),
        "corr": {
            terms[i]: {terms[j]: pearson_corr(x)[i][j] for j in range(len(terms))}
            for i in range(len(terms))
        },
    }


def format_float(value: object) -> str:
    if isinstance(value, float):
        if math.isnan(value):
            return "nan"
        if math.isinf(value):
            return "inf" if value > 0 else "-inf"
        return f"{value:.12g}"
    return str(value)


def write_markdown_summary(
    path: Path,
    summaries: list[dict[str, object]],
    coeffs: list[dict[str, object]],
    residuals: list[dict[str, object]],
    nonnegative: list[dict[str, object]],
) -> None:
    coeff_by_key: dict[tuple[str, str], list[dict[str, object]]] = {}
    for row in coeffs:
        coeff_by_key.setdefault((str(row["sim"]), str(row["model"])), []).append(row)

    lines = [
        "# NO0190 runtime cost-model regression summary",
        "",
        "Main model: `T = c_comp*sum(f*n_comp) + c_src*sum(f*n_src) + "
        "c_sink*sum(f*n_sink) + c_succ*sum(f*a_succ) + c_exam*n_supernode`.",
        "",
        "Feature scaling in coefficient tables: operation terms are fit as "
        "`ms / 1e8 ops`; display values convert them to `ps/op`. `exam` is "
        "fit as `ms/supernode` and displayed as `us/supernode`.",
        "",
    ]
    for summary in summaries:
        if summary["model"] != "main":
            continue
        sim = str(summary["sim"])
        lines += [
            f"## {sim} main model",
            "",
            "| metric | value |",
            "| --- | ---: |",
            f"| samples | {summary['n']} |",
            f"| R2 | {float(summary['r2']):.6f} |",
            f"| adjusted R2 | {float(summary['adj_r2']):.6f} |",
            f"| RMSE ms | {float(summary['rmse_ms']):.6f} |",
            f"| MAE ms | {float(summary['mae_ms']):.6f} |",
            f"| MAPE percent | {float(summary['mape_percent']):.6f} |",
            f"| LOOCV R2 | {float(summary['loocv']['r2']):.6f} |",
            f"| LOOCV RMSE ms | {float(summary['loocv']['rmse']):.6f} |",
            f"| condition number | {float(summary['condition_number']):.6f} |",
            "",
            "| term | coef | display | se | t | 95% CI |",
            "| --- | ---: | ---: | ---: | ---: | ---: |",
        ]
        for row in coeff_by_key[(sim, "main")]:
            lines.append(
                f"| {row['term']} | {float(row['coef_scaled']):.6g} "
                f"{row['unit']} | {float(row['coef_display']):.6g} "
                f"{row['display_unit']} | {float(row['se_scaled']):.6g} | "
                f"{float(row['t']):.3f} | [{float(row['ci95_low_scaled']):.6g}, "
                f"{float(row['ci95_high_scaled']):.6g}] |"
            )
        lines += ["", "Top residuals:", "", "| case | actual ms | pred ms | resid ms | verify |", "| --- | ---: | ---: | ---: | --- |"]
        for row in [r for r in residuals if r["sim"] == sim and r["model"] == "main"][:8]:
            lines.append(
                f"| {row['case']} | {float(row['actual_ms']):.3f} | "
                f"{float(row['pred_ms']):.3f} | {float(row['resid_ms']):.3f} | "
                f"{row['verify_status']} |"
            )
        lines.append("")

    lines += ["## Nonnegative subset contrast", "", "| sim | active terms | R2 | RMSE ms | MAE ms | coefficients |", "| --- | --- | ---: | ---: | ---: | --- |"]
    for row in nonnegative:
        beta = row["beta"]
        coeff_text = ", ".join(
            f"{term}={float(beta[term]) * (10.0 if term != 'exam' else 1000.0):.3g}"
            f"{'ps/op' if term != 'exam' else 'us/supernode'}"
            for term in MAIN_TERMS
        )
        lines.append(
            f"| {row['sim']} | {', '.join(row['terms'])} | {float(row['r2']):.6f} | "
            f"{float(row['rmse']):.6f} | {float(row['mae']):.6f} | {coeff_text} |"
        )
    lines.append("")
    path.write_text("\n".join(lines))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--raw-dir",
        type=Path,
        default=Path("testcase/xs-components/build/no0190_runtime_profile_20260613/raw"),
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        default=Path("testcase/xs-components/build/no0190_runtime_profile_20260613/model"),
    )
    parser.add_argument(
        "--pass-only",
        action="store_true",
        help="Exclude cases collected after verification mismatch.",
    )
    args = parser.parse_args()

    args.out_dir.mkdir(parents=True, exist_ok=True)
    all_features: list[dict[str, object]] = []
    summaries: list[dict[str, object]] = []
    coeffs: list[dict[str, object]] = []
    residuals: list[dict[str, object]] = []
    nonnegative: list[dict[str, object]] = []

    for sim in ["gsim", "grhsim"]:
        features = load_features(args.raw_dir, sim, pass_only=args.pass_only)
        all_features.extend(features)

        x, y, fit = fit_model(features, MAIN_TERMS)
        summaries.append(summarize_fit(sim, "main", MAIN_TERMS, x, y, fit))
        coeffs.extend(coefficient_rows(sim, "main", MAIN_TERMS, fit))
        residuals.extend(residual_rows(sim, "main", features, fit))

        x_const, y_const, fit_const = fit_model(features, CONST_TERMS)
        summaries.append(
            summarize_fit(sim, "with_const", CONST_TERMS, x_const, y_const, fit_const)
        )
        coeffs.extend(coefficient_rows(sim, "with_const", CONST_TERMS, fit_const))
        residuals.extend(residual_rows(sim, "with_const", features, fit_const))

        nn = best_nonnegative_subset(features, MAIN_TERMS)
        nn["sim"] = sim
        nonnegative.append(nn)

    feature_fields = [
        "case",
        "sim",
        "verify_status",
        "ms",
        "comp",
        "src",
        "sink",
        "const",
        "succ",
        "exam",
        "distinct_supernodes",
    ]
    write_tsv(args.out_dir / "case_features.tsv", all_features, feature_fields)
    write_tsv(
        args.out_dir / "coefficients.tsv",
        coeffs,
        [
            "sim",
            "model",
            "term",
            "coef_scaled",
            "se_scaled",
            "t",
            "ci95_low_scaled",
            "ci95_high_scaled",
            "unit",
            "coef_display",
            "display_unit",
        ],
    )
    write_tsv(
        args.out_dir / "residuals.tsv",
        residuals,
        [
            "sim",
            "model",
            "case",
            "verify_status",
            "actual_ms",
            "pred_ms",
            "resid_ms",
            "abs_resid_ms",
        ],
    )
    with (args.out_dir / "summary.json").open("w") as f:
        json.dump(
            {
                "raw_dir": str(args.raw_dir),
                "pass_only": args.pass_only,
                "main_terms": MAIN_TERMS,
                "const_terms": CONST_TERMS,
                "summaries": summaries,
                "nonnegative_subset": nonnegative,
            },
            f,
            indent=2,
            sort_keys=True,
        )
    write_markdown_summary(
        args.out_dir / "summary.md", summaries, coeffs, residuals, nonnegative
    )

    for row in summaries:
        if row["model"] == "main":
            print(
                f"{row['sim']} main: R2={float(row['r2']):.6f} "
                f"LOOCV_R2={float(row['loocv']['r2']):.6f} "
                f"RMSE={float(row['rmse_ms']):.3f}ms "
                f"MAPE={float(row['mape_percent']):.2f}%"
            )
    print(f"Wrote {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
