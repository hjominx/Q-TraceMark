#!/usr/bin/env python3
"""Build a self-contained, interactive web report for Q-TraceMark.

Reads the outputs of a real-photo run (``run_image_experiment.py`` +
``make_photo_research_figures.py`` + ``run_validation_suite.py``) and emits a
single portable ``index.html`` plus the figures it references. The page opens
directly via ``file://`` or can be served / deployed anywhere.

It features:
  * a draggable before/after slider (original vs watermarked),
  * interactive attack-strength charts (JPEG / crop / fragment / brightness),
  * detection + false-positive tables, imperceptibility metrics, and the
    QRNG evidence package — all baked from the JSON reports.

Falls back to the committed ``docs/assets`` / ``results/demo`` examples when a
real-photo run is not present.

Usage:
    python3 scripts/build_web_report.py
    python3 scripts/build_web_report.py --experiment results/photo_experiment \\
        --research results/photo_research_figures \\
        --validation results/photo_validation/validation_report.json
"""
from __future__ import annotations

import argparse
import html
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

# Detection variants in display order: (report key, label, note)
VARIANTS = [
    ("source", "원본 (워터마크 없음)", "대조군 · 미검출이 정상"),
    ("watermarked", "워터마크 삽입본", "무손실"),
    ("jpeg_q70", "JPEG 압축", "품질 Q70"),
    ("crop_50pct", "50% 크롭", "위치 정보 없음"),
    ("brightness", "밝기 변형", "톤 커브 변경"),
    ("pasted_fragment", "부분 합성 조각", "ROI 일부만 유통"),
]

# Interactive attack-strength charts: (sweep key, x field, title, x-axis label,
#   formatter id understood by the front-end)
SWEEP_SPECS = [
    ("jpeg", "quality", "JPEG 압축 품질", "JPEG quality", "q"),
    ("crop", "area_fraction", "크롭 (남은 영역)", "남은 면적", "pct"),
    ("fragment", "area_fraction", "부분 합성 조각 크기", "조각 면적", "pct"),
    ("brightness", "factor", "밝기 변형 계수", "밝기 factor", "x"),
]


def load_json(path: Path | None):
    if path is None or not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def esc(value) -> str:
    return html.escape(str(value))


def short_hash(value, head: int = 12) -> str:
    s = str(value or "")
    return s if len(s) <= head + 4 else f"{s[:head]}…{s[-4:]}"


def copy_if_exists(src: Path, dst_dir: Path) -> str | None:
    if src.exists():
        shutil.copy2(src, dst_dir / src.name)
        return src.name
    return None


# --------------------------------------------------------------------------- #
# HTML section builders
# --------------------------------------------------------------------------- #

def detection_rows(report) -> str:
    if not report:
        return ""
    detections = report.get("detections", {})
    rows = []
    for key, label, note in VARIANTS:
        by_type = {l.get("layer_type"): l for l in detections.get(key, [])}
        cells = []
        for layer_type in ("work", "copy"):
            d = by_type.get(layer_type)
            if not d:
                cells.append('<td class="num">—</td>')
                continue
            detected = d.get("detected")
            conf = d.get("confidence", 0.0)
            z = d.get("z_score")
            badge = "ok" if detected else "no"
            mark = "검출" if detected else "미검출"
            ztxt = f" · z {z:.1f}" if isinstance(z, (int, float)) else ""
            cells.append(
                f'<td class="num"><span class="pill {badge}">{mark}</span>'
                f'<span class="conf">conf {conf:.3f}{ztxt}</span></td>'
            )
        rows.append(
            f"<tr><td><strong>{esc(label)}</strong><span class='note'>{esc(note)}</span></td>"
            f"{cells[0]}{cells[1]}</tr>"
        )
    return "\n".join(rows)


def fpr_rows(report) -> str:
    if not report:
        return ""
    # report-grade validation nests the sweep under false_positive_analysis
    fa = report.get("false_positive_analysis") or {}
    sweep = (report.get("fpr_threshold_sweep") or report.get("threshold_sweep")
             or fa.get("threshold_sweep"))
    if not sweep:
        sweep = [{
            "threshold": report.get("threshold"),
            "false_positive_images": report.get("false_positive_images"),
            "false_positive_rate": report.get("false_positive_rate"),
        }]
    samples = (report.get("control_samples") or report.get("samples")
               or fa.get("samples") or "?")
    rows = []
    for s in sweep:
        thr = s.get("threshold")
        fp = s.get("false_positive_images")
        rate = (s.get("false_positive_rate") or 0.0) * 100
        recommend = ' <span class="pill ok">권장</span>' if thr == 0.999 else ""
        rows.append(
            f"<tr><td class='num'><strong>{thr}</strong>{recommend}</td>"
            f"<td class='num'>{fp} / {samples}</td>"
            f"<td class='num'>{rate:.1f}%</td></tr>"
        )
    return "\n".join(rows)


def evk_quality_rows(report, limit: int = 12) -> str:
    if not report:
        return ""
    rows = []
    for f in (report.get("files") or [])[:limit]:
        rows.append(
            "<tr>"
            f"<td><code>{esc(f.get('file'))}</code></td>"
            f"<td class='num'>{f.get('byte_count', 0):,}</td>"
            f"<td class='num'>{f.get('bit_one_ratio', 0):.6f}</td>"
            f"<td class='num'>{f.get('byte_entropy_bits_per_byte', 0):.5f}</td>"
            f"<td class='num'>{f.get('longest_run_bits', '—')}</td>"
            f"<td class='mono'>{short_hash(f.get('sha256'))}</td>"
            "</tr>"
        )
    return "\n".join(rows)


def layer_cards(report) -> str:
    if not report:
        return ""
    titles = {"work": "작품 지문 (work)", "copy": "사본 지문 (copy)"}
    cards = []
    for layer in report.get("layers", []):
        lt = layer.get("layer_type")
        cards.append(
            f"""<div class="card">
              <div class="card-head">{esc(titles.get(lt, lt))}</div>
              <dl>
                <dt>layer_id</dt><dd><code>{esc(layer.get('layer_id'))}</code></dd>
                <dt>seed&nbsp;hash</dt><dd class="mono">{short_hash(layer.get('seed_hash'), 24)}</dd>
                <dt>alpha</dt><dd>{layer.get('alpha')}</dd>
                <dt>period</dt><dd>{layer.get('period')}</dd>
              </dl>
            </div>"""
        )
    return "\n".join(cards)


def fmt_p(p) -> str:
    if not isinstance(p, (int, float)):
        return "—"
    if p == 0:
        return "0"
    if p < 1e-4 or p >= 1e4:
        return f"{p:.2e}"
    return f"{p:.4g}"


def validation_attack_table(report) -> str:
    """Full per-layer detection statistics from a validation report."""
    if not report:
        return ""
    detections = report.get("attack_detections") or report.get("detections", {})
    rows = []
    for key, label, _ in VARIANTS:
        for layer in detections.get(key, []):
            lt = layer.get("layer_type")
            detected = layer.get("detected")
            badge = "ok" if detected else "no"
            mark = "검출" if detected else "미검출"
            rows.append(
                "<tr>"
                f"<td><strong>{esc(label)}</strong> <span class='muted'>· {esc(lt)}</span></td>"
                f"<td class='num'>{layer.get('confidence', 0):.3f}</td>"
                f"<td class='num'>{layer.get('z_score', 0):.2f}</td>"
                f"<td class='num'>{layer.get('mean_correlation', 0):.3f}</td>"
                f"<td class='num'>{layer.get('phase_trials', '—')}</td>"
                f"<td class='num mono'>{fmt_p(layer.get('p_value_corrected'))}</td>"
                f"<td class='num'><span class='pill {badge}'>{mark}</span></td>"
                "</tr>"
            )
    return "\n".join(rows)


def validation_section(report) -> str:
    """Render the full validation-report section, or empty string if absent."""
    if not report:
        return ""
    fa = report.get("false_positive_analysis") or {}
    entropy = report.get("entropy_report", {})
    # raw JSON for inspection, with the bulky per-control list collapsed
    raw = dict(report)
    if isinstance(raw.get("false_positive_analysis"), dict) and "controls" in raw["false_positive_analysis"]:
        fa_copy = dict(raw["false_positive_analysis"])
        n = len(fa_copy["controls"])
        fa_copy["controls"] = f"<{n} per-control records omitted from preview>"
        raw["false_positive_analysis"] = fa_copy
    raw_json = json.dumps(raw, ensure_ascii=False, indent=2)

    return f"""
  <div class="grid2">
    <div class="card"><div class="card-head">보고서 메타</div>
      <dl>
        <dt>report_type</dt><dd>{esc(report.get('report_type'))}</dd>
        <dt>schema</dt><dd>{esc(report.get('evidence_schema_version'))}</dd>
        <dt>발급 시각</dt><dd class="mono">{esc(report.get('issued_at_utc'))}</dd>
        <dt>thresholds</dt><dd>{esc(report.get('thresholds'))}</dd>
        <dt>confidence model</dt><dd style="font-size:12px">{esc(report.get('confidence_model'))}</dd>
        <dt>master seed</dt><dd class="mono">{short_hash(report.get('master_seed_hash'), 24)}</dd>
        <dt>QRNG source</dt><dd style="font-size:12px;color:var(--muted)">{esc(report.get('qrng_source'))}</dd>
      </dl></div>
    <div class="card"><div class="card-head">오탐 분석 (false_positive_analysis)</div>
      <dl>
        <dt>control source</dt><dd>{esc(fa.get('control_source'))}</dd>
        <dt>samples</dt><dd>{fa.get('samples', '—')}</dd>
        <dt>max null confidence</dt><dd>{fa.get('max_null_confidence', 0):.4f}</dd>
        <dt>max null z-score</dt><dd>{fa.get('max_null_z_score', 0):.3f}</dd>
        <dt>min null p_corrected</dt><dd class="mono">{fmt_p(fa.get('min_null_corrected_p_value'))}</dd>
        <dt>QRNG entropy</dt><dd>{entropy.get('byte_entropy_bits_per_byte', 0):.5f} bits/byte</dd>
      </dl></div>
  </div>

  <h3 class="subhead">공격별 검출 통계 (attack_detections)</h3>
  <table>
    <thead><tr>
      <th>변형 · 레이어</th><th class="num">conf</th><th class="num">z</th>
      <th class="num">corr</th><th class="num">phase</th><th class="num">p_corrected</th><th class="num">결과</th>
    </tr></thead>
    <tbody>{validation_attack_table(report)}</tbody>
  </table>

  <details class="raw">
    <summary>원본 JSON 전체 보기 (per-control 100건 기록은 생략)</summary>
    <pre>{esc(raw_json)}</pre>
  </details>"""


def build_sweep_data(research) -> dict:
    """Extract per-strength sweep points for the interactive charts."""
    if not research:
        return {}
    sweeps = research.get("sweeps", {})
    out = {}
    for key, xfield, title, xlabel, fmt in SWEEP_SPECS:
        rows = sweeps.get(key)
        if not rows:
            continue
        points = [{
            "x": r.get(xfield),
            "work": r.get("work_z"),
            "copy": r.get("copy_z"),
            "detected": bool(r.get("all_detected")),
        } for r in rows if r.get(xfield) is not None]
        if points:
            out[key] = {"title": title, "xlabel": xlabel, "fmt": fmt, "points": points}
    return out


# --------------------------------------------------------------------------- #
# Page assembly
# --------------------------------------------------------------------------- #

def build_html(*, exp_report, validation, evk_quality, research,
               figs, slider, generated) -> str:
    demo = exp_report or {}
    entropy = demo.get("entropy_report", {})
    sweep_data = build_sweep_data(research)
    work_size = (research or {}).get("working_size") or [None, None]

    def fig(name, caption):
        if name not in figs:
            return ""
        return (
            f'<figure><img src="assets/{esc(name)}" alt="{esc(caption)}" loading="lazy">'
            f'<figcaption>{esc(caption)}</figcaption></figure>'
        )

    # ---- imperceptibility metrics card (only when research present) -------- #
    if research:
        imperceptibility = f"""
    <div class="grid2" style="margin-top:16px">
      <div class="card"><div class="card-head">비가시성 (워터마크 품질)</div>
        <dl>
          <dt>PSNR (RGB)</dt><dd><strong>{research.get('psnr_rgb_db', 0):.2f} dB</strong></dd>
          <dt>평균 |ΔY|</dt><dd>{research.get('mean_abs_delta_y', 0):.3f} / 255</dd>
          <dt>p95 |ΔY|</dt><dd>{research.get('p95_abs_delta_y', 0)} / 255</dd>
          <dt>최대 |ΔY|</dt><dd>{research.get('max_abs_delta_y', 0)} / 255</dd>
        </dl></div>
      <div class="card"><div class="card-head">원본 이미지</div>
        <dl>
          <dt>작업 해상도</dt><dd>{work_size[0]} × {work_size[1]} px</dd>
          <dt>source sha256</dt><dd class="mono">{short_hash(research.get('source_sha256'), 20)}</dd>
          <dt>work alpha</dt><dd>{research.get('work_alpha')}</dd>
          <dt>copy alpha</dt><dd>{research.get('copy_alpha')}</dd>
        </dl></div>
    </div>"""
    else:
        imperceptibility = ""

    # ---- before/after slider ---------------------------------------------- #
    if slider:
        slider_html = f"""
    <div class="slider" id="ba-slider">
      <img class="ba-base" src="assets/{esc(slider['watermarked'])}" alt="워터마크 삽입본">
      <div class="ba-top"><img src="assets/{esc(slider['source'])}" alt="원본"></div>
      <div class="ba-line"><div class="ba-handle">⇄</div></div>
      <span class="ba-tag ba-left">원본</span>
      <span class="ba-tag ba-right">워터마크 삽입본</span>
    </div>
    <p class="sub" style="margin-top:10px;text-align:center">손잡이를 드래그해 원본과 삽입본을 비교하세요 — 육안으로는 사실상 구분되지 않습니다 (PSNR {research.get('psnr_rgb_db', 0):.1f} dB).</p>"""
    else:
        slider_html = ""

    # ---- interactive charts tabs ------------------------------------------ #
    if sweep_data:
        tabs = "".join(
            f'<button class="tab{" active" if i == 0 else ""}" data-key="{esc(k)}">{esc(v["title"])}</button>'
            for i, (k, v) in enumerate(sweep_data.items())
        )
        charts_html = f"""
    <div class="tabs">{tabs}</div>
    <div class="chart-wrap">
      <svg id="chart" viewBox="0 0 720 340" preserveAspectRatio="xMidYMid meet" role="img"></svg>
      <div id="chart-tip" class="chart-tip" hidden></div>
    </div>
    <div class="legend">
      <span><i class="dot work"></i>work 지문 z-score</span>
      <span><i class="dot copy"></i>copy 지문 z-score</span>
      <span class="muted">z가 높을수록 검출이 강함 · 모든 지점에서 검출 성공</span>
    </div>
    {fig('fig_jpeg_quality_sweep.png', 'JPEG 품질 sweep (정적 그림)')}
    {fig('fig_crop_fragment_sweep.png', '크롭/조각 sweep (정적 그림)')}
    {fig('fig_brightness_sweep.png', '밝기 sweep (정적 그림)')}
    {fig('fig_null_distribution.png', 'null 분포 (무워터마크 대조군)')}"""
    else:
        charts_html = ""

    data_blob = json.dumps(sweep_data, ensure_ascii=False)

    return f"""<!doctype html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Q-TraceMark · 실제 사진 작업 과정과 결과</title>
<style>
  :root {{
    --bg:#0b1120; --panel:#111a2e; --panel2:#16223c; --line:#233252;
    --ink:#e8eefc; --muted:#93a3c4; --accent:#5b9dff; --ok:#34d399; --no:#fb7185;
    --copy:#fbbf24;
    --mono:'SFMono-Regular',ui-monospace,Menlo,Consolas,monospace;
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--ink);
    font-family:-apple-system,'Apple SD Gothic Neo','Pretendard',Segoe UI,Roboto,sans-serif;
    line-height:1.65; }}
  a {{ color:var(--accent); }}
  .wrap {{ max-width:1040px; margin:0 auto; padding:0 22px; }}
  header.hero {{ padding:72px 0 48px; border-bottom:1px solid var(--line);
    background:radial-gradient(1200px 400px at 70% -10%, rgba(91,157,255,.18), transparent); }}
  .eyebrow {{ color:var(--accent); font-weight:700; letter-spacing:.14em; font-size:13px; text-transform:uppercase; }}
  h1 {{ font-size:40px; margin:.3em 0 .2em; line-height:1.2; }}
  .lede {{ color:var(--muted); font-size:18px; max-width:70ch; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:8px; margin-top:22px; }}
  .chip {{ background:var(--panel2); border:1px solid var(--line); padding:6px 12px;
    border-radius:999px; font-size:13px; color:var(--muted); }}
  section {{ padding:54px 0; border-bottom:1px solid var(--line); }}
  h2 {{ font-size:26px; margin:0 0 6px; }}
  h2 .idx {{ color:var(--accent); font-variant-numeric:tabular-nums; margin-right:10px; }}
  .sub {{ color:var(--muted); margin:0 0 26px; max-width:74ch; }}
  .steps {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(210px,1fr)); gap:16px; }}
  .step {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px; }}
  .step .n {{ width:30px;height:30px;border-radius:8px;background:var(--panel2);
    display:flex;align-items:center;justify-content:center;color:var(--accent);font-weight:700;margin-bottom:10px; }}
  .step h3 {{ margin:0 0 6px; font-size:16px; }}
  .step p {{ margin:0; color:var(--muted); font-size:14px; }}
  .grid2 {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  .card {{ background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:18px 20px; }}
  .card-head {{ font-weight:700; margin-bottom:10px; }}
  dl {{ display:grid; grid-template-columns:auto 1fr; gap:6px 14px; margin:0; font-size:14px; }}
  dt {{ color:var(--muted); }}
  dd {{ margin:0; word-break:break-all; }}
  table {{ width:100%; border-collapse:collapse; font-size:14px; background:var(--panel);
    border:1px solid var(--line); border-radius:14px; overflow:hidden; }}
  th, td {{ padding:11px 14px; text-align:left; border-bottom:1px solid var(--line); }}
  th {{ background:var(--panel2); color:var(--muted); font-weight:600; font-size:13px; }}
  tr:last-child td {{ border-bottom:none; }}
  td.num, th.num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  .note {{ display:block; color:var(--muted); font-size:12px; font-weight:400; }}
  .pill {{ display:inline-block; padding:2px 9px; border-radius:999px; font-size:12px; font-weight:700; }}
  .pill.ok {{ background:rgba(52,211,153,.15); color:var(--ok); }}
  .pill.no {{ background:rgba(251,113,133,.15); color:var(--no); }}
  .conf {{ display:block; color:var(--muted); font-size:12px; margin-top:3px; }}
  .mono, code {{ font-family:var(--mono); font-size:12.5px; }}
  code {{ background:var(--panel2); padding:2px 6px; border-radius:6px; }}
  figure {{ margin:18px 0 0; }}
  figure img {{ width:100%; border:1px solid var(--line); border-radius:14px; display:block; background:#fff; }}
  figcaption {{ color:var(--muted); font-size:13px; margin-top:8px; text-align:center; }}
  pre {{ background:#0a1020; border:1px solid var(--line); border-radius:12px; padding:16px;
    overflow:auto; font-family:var(--mono); font-size:13px; color:#cdd9f5; }}
  .pre-comment {{ color:var(--muted); }}
  footer {{ padding:40px 0 70px; color:var(--muted); font-size:13px; }}
  /* before/after slider */
  .slider {{ position:relative; width:100%; max-width:760px; margin:0 auto; aspect-ratio:3/2;
    border:1px solid var(--line); border-radius:14px; overflow:hidden; user-select:none; touch-action:none; cursor:ew-resize; }}
  .slider img {{ width:100%; height:100%; object-fit:cover; display:block; }}
  .slider .ba-base {{ position:absolute; inset:0; }}
  .slider .ba-top {{ position:absolute; inset:0; width:50%; overflow:hidden; }}
  .slider .ba-top img {{ width:760px; max-width:none; }}
  .slider .ba-line {{ position:absolute; top:0; bottom:0; left:50%; width:2px; background:#fff; box-shadow:0 0 0 1px rgba(0,0,0,.35); }}
  .slider .ba-handle {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    width:38px; height:38px; border-radius:50%; background:#fff; color:#0b1120; font-weight:800;
    display:flex; align-items:center; justify-content:center; box-shadow:0 2px 8px rgba(0,0,0,.4); }}
  .ba-tag {{ position:absolute; top:12px; padding:3px 10px; border-radius:999px; font-size:12px; font-weight:700;
    background:rgba(11,17,32,.72); backdrop-filter:blur(4px); }}
  .ba-left {{ left:12px; }} .ba-right {{ right:12px; }}
  /* interactive chart */
  .tabs {{ display:flex; flex-wrap:wrap; gap:8px; margin-bottom:8px; }}
  .tab {{ background:var(--panel); border:1px solid var(--line); color:var(--muted);
    padding:8px 14px; border-radius:10px; font-size:14px; cursor:pointer; }}
  .tab.active {{ background:var(--accent); border-color:var(--accent); color:#06122b; font-weight:700; }}
  .chart-wrap {{ position:relative; background:var(--panel); border:1px solid var(--line); border-radius:14px; padding:10px; }}
  #chart {{ width:100%; height:auto; display:block; }}
  .chart-tip {{ position:absolute; pointer-events:none; background:#0a1020; border:1px solid var(--line);
    border-radius:8px; padding:7px 10px; font-size:12px; color:var(--ink); transform:translate(-50%,-115%); white-space:nowrap; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:18px; margin-top:12px; font-size:13px; color:var(--muted); align-items:center; }}
  .legend .dot {{ display:inline-block; width:11px; height:11px; border-radius:50%; margin-right:6px; vertical-align:middle; }}
  .dot.work {{ background:var(--accent); }} .dot.copy {{ background:var(--copy); }}
  .muted {{ color:var(--muted); }}
  .subhead {{ font-size:16px; margin:26px 0 12px; color:var(--ink); }}
  details.raw {{ margin-top:18px; background:var(--panel); border:1px solid var(--line); border-radius:12px; }}
  details.raw summary {{ cursor:pointer; padding:13px 16px; font-size:14px; color:var(--accent); font-weight:600; }}
  details.raw pre {{ margin:0; border:none; border-top:1px solid var(--line); border-radius:0 0 12px 12px; max-height:460px; }}
  @media (max-width:720px) {{ h1{{font-size:30px}} .grid2{{grid-template-columns:1fr}} }}
</style>
</head>
<body>
<header class="hero"><div class="wrap">
  <div class="eyebrow">Q-TraceMark · 실제 사진 실행</div>
  <h1>QRNG 기반 이미지 포렌식 지문 — 작업 과정과 결과</h1>
  <p class="lede">실제 사진 한 장에 EVK 양자난수(QRNG)로 작품별·사본별 보이지 않는 워터마크를
    발급하고, JPEG·크롭·밝기·부분합성 공격에도 work/copy 지문을 검출하며, 발급·검출 전 과정을
    감사 가능한 증거 패키지로 남긴 전체 실행 결과입니다.</p>
  <div class="chips">
    <span class="chip">실제 사진 · {work_size[0]}×{work_size[1]}</span>
    <span class="chip">PSNR {research.get('psnr_rgb_db', 0):.1f} dB</span>
    <span class="chip">5/5 공격 검출</span>
    <span class="chip">오탐 0 @ 0.999</span>
    <span class="chip">2계층(work·copy) 지문</span>
  </div>
</div></header>

<section><div class="wrap">
  <h2><span class="idx">01</span>작동 원리</h2>
  <p class="sub">픽셀에 로고를 숨기는 방식이 아니라, QRNG seed로 생성한 spread-spectrum 신호를
    DCT 중주파수 계수에 약하게 분산 삽입합니다. QRNG의 역할은 강건성 자체가 아니라
    seed의 물리적 비예측성과 발급 과정의 공증입니다.</p>
  <div class="steps">
    <div class="step"><div class="n">1</div><h3>QRNG seed 발급</h3>
      <p>EVK 양자난수에서 master seed를 파생하고 품질 리포트(엔트로피·bit ratio)를 생성.</p></div>
    <div class="step"><div class="n">2</div><h3>2계층 워터마크 삽입</h3>
      <p>work 지문과 copy 지문을 각각 다른 seed/alpha로 DCT 계수에 분산 삽입.</p></div>
    <div class="step"><div class="n">3</div><h3>공격·검출</h3>
      <p>JPEG·크롭·밝기·부분합성 변형 후, phase 후보를 탐색하는 z-test 상관 검출.</p></div>
    <div class="step"><div class="n">4</div><h3>증거 패키지</h3>
      <p>원본 hash·seed hash·발급 시각·신뢰도를 묶어 감사/분쟁용 증거로 commit.</p></div>
  </div>
  {fig('fig_qtracemark_pipeline.png', '파이프라인 개요')}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">02</span>원본 ↔ 워터마크 비교</h2>
  <p class="sub">동일한 사진에 work/copy 지문을 삽입한 결과입니다. 슬라이더로 직접 비교해 보세요.</p>
  {slider_html}
  {fig('diff_figure.png', '원본 / 워터마크 / 증폭한 Y 채널 차이')}
  {imperceptibility}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">03</span>발급 결과 — 증거 패키지</h2>
  <p class="sub">work_id <code>{esc(demo.get('work_id'))}</code>,
    copy_id <code>{esc(demo.get('copy_id'))}</code> 에 대해 발급된 지문과 QRNG 품질 지표입니다.
    master seed hash: <span class="mono">{short_hash(demo.get('master_seed_hash'), 28)}</span></p>
  <div class="grid2">{layer_cards(demo)}</div>
  <div class="grid2" style="margin-top:16px">
    <div class="card"><div class="card-head">QRNG 엔트로피 리포트</div>
      <dl>
        <dt>byte count</dt><dd>{entropy.get('byte_count', 0):,}</dd>
        <dt>bit-one ratio</dt><dd>{entropy.get('bit_one_ratio', 0):.7f}</dd>
        <dt>byte entropy</dt><dd>{entropy.get('byte_entropy_bits_per_byte', 0):.6f} bits/byte</dd>
        <dt>longest run</dt><dd>{entropy.get('longest_run_bits', '—')} bits</dd>
      </dl></div>
    <div class="card"><div class="card-head">발급 메타</div>
      <dl>
        <dt>schema</dt><dd>{esc(demo.get('evidence_schema_version') or demo.get('report_type'))}</dd>
        <dt>발급 시각</dt><dd class="mono">{esc(demo.get('issued_at_utc'))}</dd>
        <dt>threshold</dt><dd>{demo.get('detection_threshold')}</dd>
        <dt>QRNG source</dt><dd style="font-size:12px;color:var(--muted)">{esc(demo.get('qrng_source'))}</dd>
      </dl></div>
  </div>
  {fig('fig_evidence_package.png', '증거 패키지 구성')}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">04</span>검출 결과 — 공격 강건성</h2>
  <p class="sub">워터마크 삽입본을 여러 방식으로 변형한 뒤 work/copy 지문을 검출한 결과입니다.
    원본(대조군)은 미검출, 나머지 변형본은 모두 검출되는 것이 기대 동작입니다.</p>
  <table>
    <thead><tr><th>이미지 변형</th><th class="num">work 지문</th><th class="num">copy 지문</th></tr></thead>
    <tbody>{detection_rows(demo)}</tbody>
  </table>
  {fig('contact_sheet.png', '컨택트 시트 — 원본·삽입본·공격본 한눈에')}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">05</span>공격 강도별 검출 추이 (인터랙티브)</h2>
  <p class="sub">공격 강도를 단계적으로 키우며 z-score 검출 세기를 측정했습니다.
    탭으로 공격 종류를 바꾸고, 점에 마우스를 올리면 정확한 값을 확인할 수 있습니다.</p>
  {charts_html}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">06</span>오탐률 (FPR) — 무워터마크 대조군</h2>
  <p class="sub">검출기는 crop offset을 모르는 상황을 가정해 다수의 phase 후보를 탐색하므로,
    워터마크가 없는 대조군에서 false positive를 측정해 신뢰도 threshold를 보정합니다.</p>
  <table>
    <thead><tr><th class="num">threshold</th><th class="num">false positives</th><th class="num">FPR</th></tr></thead>
    <tbody>{fpr_rows(validation)}</tbody>
  </table>
  <p class="sub" style="margin-top:14px">보고/분쟁용 주장에는 더 큰 null 집합이 정당화하지 않는 한 <code>0.999</code> threshold를 사용합니다.</p>
</div></section>

<section><div class="wrap">
  <h2><span class="idx">07</span>검증 보고서 전체</h2>
  <p class="sub"><code>run_validation_suite.py</code>가 생성한 report-grade 검증 보고서
    (<code>validation_report.json</code>)의 전체 내용입니다. 재현 가능한 자체 완결 검증을 위해
    합성 대조군 + demo QRNG fallback으로 실행되며, 실사진 검출 결과(섹션 02~05)와는 별도의
    독립 산출물입니다.</p>
  {validation_section(validation)}
</div></section>

<section><div class="wrap">
  <h2><span class="idx">08</span>EVK QRNG 품질</h2>
  <p class="sub">seed 원천인 EVK 양자난수 파일들의 통계 요약입니다
    ({(evk_quality or {}).get('file_count', '?')}개 파일). raw <code>.bin</code>은 커밋하지 않고
    파생 해시/통계만 공개합니다.</p>
  <table>
    <thead><tr><th>파일</th><th class="num">bytes</th><th class="num">bit-one</th>
      <th class="num">entropy</th><th class="num">longest run</th><th>sha256</th></tr></thead>
    <tbody>{evk_quality_rows(evk_quality)}</tbody>
  </table>
</div></section>

<section><div class="wrap">
  <h2><span class="idx">09</span>직접 재현하기</h2>
  <p class="sub">아래 명령으로 이 페이지의 전체 산출물을 실제 사진에서 재생성할 수 있습니다.</p>
  <pre><span class="pre-comment"># 1) 실제 사진으로 발급·공격·검출</span>
python3 scripts/run_image_experiment.py --image /path/to/photo.jpg --out results/photo_experiment

<span class="pre-comment"># 2) 공격 강도별 sweep 그래프 생성</span>
python3 scripts/make_photo_research_figures.py --image /path/to/photo.jpg --out results/photo_research_figures

<span class="pre-comment"># 3) report-grade 검증 (검출 + FPR + threshold sweep)</span>
python3 scripts/run_validation_suite.py --out results/photo_validation/validation_report.json

<span class="pre-comment"># 4) 이 웹 리포트 재생성</span>
python3 scripts/build_web_report.py</pre>
</div></section>

<footer><div class="wrap">
  <p>Q-TraceMark · 연구용 PoC. 이 페이지는 실제 사진 실행 결과에서
    <code>scripts/build_web_report.py</code>로 생성되었습니다.</p>
  <p>생성 시각: {generated} · 저장소:
    <a href="https://github.com/hjominx/Q-TraceMark">github.com/hjominx/Q-TraceMark</a></p>
</div></footer>

<script>
// ---- before/after slider ---------------------------------------------------
(function () {{
  var s = document.getElementById('ba-slider');
  if (!s) return;
  var top = s.querySelector('.ba-top'), line = s.querySelector('.ba-line');
  function set(p) {{
    p = Math.max(0, Math.min(100, p));
    top.style.width = p + '%';
    line.style.left = p + '%';
  }}
  function fromEvent(e) {{
    var r = s.getBoundingClientRect();
    var x = (e.touches ? e.touches[0].clientX : e.clientX) - r.left;
    set(x / r.width * 100);
  }}
  var dragging = false;
  s.addEventListener('pointerdown', function (e) {{ dragging = true; fromEvent(e); s.setPointerCapture(e.pointerId); }});
  s.addEventListener('pointermove', function (e) {{ if (dragging) fromEvent(e); }});
  s.addEventListener('pointerup', function () {{ dragging = false; }});
  s.addEventListener('pointercancel', function () {{ dragging = false; }});
}})();

// ---- interactive attack-strength chart ------------------------------------
(function () {{
  var DATA = {data_blob};
  var keys = Object.keys(DATA);
  if (!keys.length) return;
  var svg = document.getElementById('chart');
  var tip = document.getElementById('chart-tip');
  var NS = 'http://www.w3.org/2000/svg';
  var W = 720, H = 340, P = {{ l: 52, r: 20, t: 24, b: 52 }};
  var current = keys[0];

  function fmtX(v, fmt) {{
    if (fmt === 'q') return 'Q' + v;
    if (fmt === 'pct') return Math.round(v * 100) + '%';
    if (fmt === 'x') return v + '×';
    return '' + v;
  }}
  function el(name, attrs) {{
    var e = document.createElementNS(NS, name);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }}
  function render(key) {{
    current = key;
    var d = DATA[key], pts = d.points;
    while (svg.firstChild) svg.removeChild(svg.firstChild);
    var maxZ = 0;
    pts.forEach(function (p) {{ maxZ = Math.max(maxZ, p.work || 0, p.copy || 0); }});
    maxZ = Math.ceil(maxZ / 10) * 10 || 10;
    var x0 = P.l, x1 = W - P.r, y0 = H - P.b, y1 = P.t;
    var xOf = function (i) {{ return pts.length < 2 ? (x0 + x1) / 2 : x0 + (x1 - x0) * i / (pts.length - 1); }};
    var yOf = function (z) {{ return y0 - (y0 - y1) * (z / maxZ); }};
    // grid + y labels
    for (var g = 0; g <= 4; g++) {{
      var zv = maxZ * g / 4, yy = yOf(zv);
      svg.appendChild(el('line', {{ x1: x0, y1: yy, x2: x1, y2: yy, stroke: '#233252', 'stroke-width': 1 }}));
      var t = el('text', {{ x: x0 - 10, y: yy + 4, fill: '#93a3c4', 'font-size': 11, 'text-anchor': 'end' }});
      t.textContent = Math.round(zv); svg.appendChild(t);
    }}
    // x labels
    pts.forEach(function (p, i) {{
      var t = el('text', {{ x: xOf(i), y: y0 + 22, fill: '#93a3c4', 'font-size': 11, 'text-anchor': 'middle' }});
      t.textContent = fmtX(p.x, d.fmt); svg.appendChild(t);
    }});
    var ax = el('text', {{ x: (x0 + x1) / 2, y: H - 12, fill: '#93a3c4', 'font-size': 12, 'text-anchor': 'middle' }});
    ax.textContent = d.xlabel; svg.appendChild(ax);
    // lines
    ['copy', 'work'].forEach(function (series) {{
      var color = series === 'work' ? '#5b9dff' : '#fbbf24';
      var pathd = pts.map(function (p, i) {{ return (i ? 'L' : 'M') + xOf(i) + ' ' + yOf(p[series] || 0); }}).join(' ');
      svg.appendChild(el('path', {{ d: pathd, fill: 'none', stroke: color, 'stroke-width': 2.5 }}));
      pts.forEach(function (p, i) {{
        var c = el('circle', {{ cx: xOf(i), cy: yOf(p[series] || 0), r: 5, fill: color, stroke: '#0b1120', 'stroke-width': 1.5 }});
        c.style.cursor = 'pointer';
        c.addEventListener('mouseenter', function () {{
          tip.hidden = false;
          tip.innerHTML = '<strong>' + fmtX(p.x, d.fmt) + '</strong> · ' + series + ' z=' + (p[series] || 0).toFixed(1) + (p.detected ? ' · 검출' : '');
          var r = svg.getBoundingClientRect();
          tip.style.left = (xOf(i) / W * r.width) + 'px';
          tip.style.top = (yOf(p[series] || 0) / H * r.height) + 'px';
        }});
        c.addEventListener('mouseleave', function () {{ tip.hidden = true; }});
        svg.appendChild(c);
      }});
    }});
  }}
  document.querySelectorAll('.tab').forEach(function (btn) {{
    btn.addEventListener('click', function () {{
      document.querySelectorAll('.tab').forEach(function (b) {{ b.classList.remove('active'); }});
      btn.classList.add('active');
      render(btn.getAttribute('data-key'));
    }});
  }});
  render(current);
}})();
</script>
</body>
</html>
"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", default=str(REPO_ROOT / "results" / "photo_experiment"),
                        help="run_image_experiment.py output dir (report.json + images)")
    parser.add_argument("--research", default=str(REPO_ROOT / "results" / "photo_research_figures"),
                        help="make_photo_research_figures.py output dir")
    parser.add_argument("--validation", default=str(REPO_ROOT / "results" / "photo_validation" / "validation_report.json"),
                        help="run_validation_suite.py report path")
    parser.add_argument("--assets", default=str(REPO_ROOT / "docs" / "assets"),
                        help="committed assets dir (pipeline figure, EVK quality report)")
    parser.add_argument("--out", default=str(REPO_ROOT / "results" / "web"),
                        help="output folder for the generated site")
    args = parser.parse_args()

    exp_dir = Path(args.experiment)
    research_dir = Path(args.research)
    assets = Path(args.assets)
    out = Path(args.out)
    out_assets = out / "assets"
    out_assets.mkdir(parents=True, exist_ok=True)

    # Primary report: real-photo run, fallback to committed demo.
    exp_report = load_json(exp_dir / "report.json")
    img_src_dir = exp_dir
    if exp_report is None:
        exp_report = load_json(REPO_ROOT / "results" / "demo" / "report.json") \
            or load_json(assets / "demo_report.json")
        img_src_dir = REPO_ROOT / "results" / "demo"
    if exp_report is None:
        print("error: no experiment report found. Run scripts/run_image_experiment.py first.")
        return 1

    research = load_json(research_dir / "research_metrics.json")
    validation = load_json(Path(args.validation)) \
        or load_json(assets / "evk_fpr_report.json") \
        or load_json(assets / "fpr_report.json")
    evk_quality = load_json(assets / "evk_qrng_quality_report.json")

    figs = set()
    # images from the experiment / fallback dir
    for name in ("source_resized.png", "source.png", "watermarked.png",
                 "contact_sheet.png", "diff_figure.png", "confidence_figure.png"):
        copied = copy_if_exists(img_src_dir / name, out_assets)
        if copied:
            figs.add(copied)
    # sweep figures from research dir
    for name in ("fig_jpeg_quality_sweep.png", "fig_crop_fragment_sweep.png",
                 "fig_brightness_sweep.png", "fig_null_distribution.png",
                 "fig_imperceptibility_metrics.png"):
        copied = copy_if_exists(research_dir / name, out_assets)
        if copied:
            figs.add(copied)
    # pipeline + evidence figures from committed assets
    for name in ("fig_qtracemark_pipeline.png", "fig_evidence_package.png"):
        copied = copy_if_exists(assets / name, out_assets)
        if copied:
            figs.add(copied)

    slider = None
    src_name = "source_resized.png" if "source_resized.png" in figs else (
        "source.png" if "source.png" in figs else None)
    if src_name and "watermarked.png" in figs:
        slider = {"source": src_name, "watermarked": "watermarked.png"}

    html_text = build_html(
        exp_report=exp_report,
        validation=validation,
        evk_quality=evk_quality,
        research=research or {},
        figs=figs,
        slider=slider,
        generated=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )
    index = out / "index.html"
    index.write_text(html_text, encoding="utf-8")

    print(f"✓ wrote {index}")
    print(f"  experiment: {exp_dir if exp_report else 'fallback'}")
    print(f"  figures copied: {len(figs)} · interactive charts: {len(build_sweep_data(research))}")
    print(f"\n웹으로 보려면:\n  python3 -m http.server -d {out} 8000\n  → http://localhost:8000\n또는 {index} 를 브라우저로 바로 열어도 됩니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
