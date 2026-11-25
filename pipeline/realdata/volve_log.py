"""Кадр класса A «реальные данные»: планшет каротажа Volve (Equinor) для шага курса.

  py -3 realdata/volve_log.py --lfp <159-19A_LFP.las> --cpi <15_9-19_A_CPI.las> --chapter train_latyshova \
      --node latyshova.terrigenous-reservoir-identification

Рисуется кодом из LAS-файлов (без генерации). Границы коллектора и насыщение — из интерпретации Equinor
(SAND_FLAG, SW в CPI), а не придуманные нами пороги. Цвета кривых — из стайлгайда организаторов.
Данные: «Данные Volve, Equinor ASA и бывшие партнёры по лицензии Volve» (для учёбы, без перепродажи).
"""
import argparse
import json
import sys
from pathlib import Path

import lasio
import matplotlib
import numpy as np

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

HERE = Path(__file__).resolve().parent.parent
SOURCE = "Данные Volve, Equinor ASA и бывшие партнёры по лицензии Volve; скв. 15/9-19 A"


def curve(las, name):
    v = np.asarray(las[name], dtype=float)
    v[v <= -999] = np.nan
    return v


def window(depth, sand, sw, span=120.0):
    """Окно глубин вокруг самого «нефтенасыщенного» песчаного интервала по интерпретации Equinor."""
    score = np.where((sand > 0.5) & np.isfinite(sw), 1 - sw, 0)
    k = int(np.argmax(np.convolve(np.nan_to_num(score), np.ones(200), mode="same")))
    c = depth[k]
    return c - span / 2, c + span / 2


def draw(lfp_path: Path, cpi_path: Path, out_png: Path) -> dict:
    lfp, cpi = lasio.read(str(lfp_path)), lasio.read(str(cpi_path))
    style = json.loads((HERE / "domain" / "geology" / "official" / "styleguide.json").read_text(encoding="utf-8"))
    col = {k: v["color"] for k, v in style["curves"].items()}
    bg, panel, ink, muted = style["background"], style["panel"], style["text"], style["muted"]
    sand_c, oil_c, water_c = style["lithology"]["sand"]["color"], style["fluids"]["oil"]["color"], style["fluids"]["water"]["color"]

    d1, d2 = lfp.index, cpi.index
    gr, rt, rhob, nphi = (curve(lfp, n) for n in ("LFP_GR", "LFP_RT", "LFP_RHOB", "LFP_NPHI"))
    sw = np.interp(d1, d2, np.nan_to_num(curve(cpi, "SW"), nan=1.0), left=np.nan, right=np.nan)
    sand = np.interp(d1, d2, np.nan_to_num(curve(cpi, "SAND_FLAG")), left=0, right=0)
    top, bot = window(d1, sand, sw)
    m = (d1 >= top) & (d1 <= bot)
    d, gr, rt, rhob, nphi, sw, sand = d1[m], gr[m], rt[m], rhob[m], nphi[m], sw[m], sand[m]

    plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 11, "text.color": ink, "axes.labelcolor": ink,
                         "xtick.color": muted, "ytick.color": muted, "axes.edgecolor": muted})
    fig, ax = plt.subplots(1, 4, figsize=(11, 8.5), sharey=True, gridspec_kw={"width_ratios": [1, 1, 1.2, 0.8]})
    fig.patch.set_facecolor(bg)
    for a in ax:
        a.set_facecolor(panel)
        a.grid(color="#2A3440", lw=0.6)
        for s in np.where(np.diff(np.r_[0, (sand > 0.5).astype(int), 0]) != 0)[0].reshape(-1, 2) if (sand > 0.5).any() else []:
            a.axhspan(d[s[0]], d[min(s[1], len(d) - 1)], color=sand_c, alpha=0.18, lw=0)
    ax[0].plot(gr, d, color=col["GR"], lw=1.2)
    ax[0].set_xlim(0, 150)
    ax[0].set_xlabel("ГК, API")
    ax[1].plot(rt, d, color=col["RES"], lw=1.2)
    ax[1].set_xscale("log")
    ax[1].set_xlim(0.2, 200)
    ax[1].set_xlabel("Сопротивление пласта, Ом·м")
    ax[2].plot(rhob, d, color=col["DENSITY"], lw=1.2, label="ГГК-П, г/см³")
    ax[2].set_xlim(1.95, 2.95)
    ax[2].set_xlabel("ГГК-П, г/см³  /  НГК (в долях)")
    tw = ax[2].twiny()
    tw.plot(nphi, d, color=col["NEUTRON"], lw=1.2)
    tw.set_xlim(0.45, -0.15)
    tw.tick_params(colors=muted)
    ax[3].fill_betweenx(d, 0, 1 - np.nan_to_num(sw, nan=1.0), color=oil_c, alpha=0.9, lw=0)
    ax[3].fill_betweenx(d, 1 - np.nan_to_num(sw, nan=1.0), 1, color=water_c, alpha=0.6, lw=0)
    ax[3].set_xlim(0, 1)
    ax[3].set_xlabel("Насыщение: нефть / вода\n(интерпретация Equinor)")
    ax[0].set_ylim(bot, top)  # глубина растёт вниз
    ax[0].set_ylabel("Глубина по стволу, м")
    fig.suptitle("Реальная скважина: где коллектор и что в нём", color=ink, fontsize=15, x=0.02, ha="left")
    fig.text(0.98, 0.965, "реальные данные", color=bg, fontsize=11, ha="right",
             bbox={"boxstyle": "round,pad=0.35", "fc": style["provenance"]["реальные данные"], "ec": "none"})
    fig.text(0.02, 0.012, SOURCE + ". Жёлтая заливка — песчаник-коллектор по интерпретации Equinor.", color=muted, fontsize=9)
    fig.tight_layout(rect=(0, 0.03, 1, 0.94))
    out_png.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_png, dpi=110, facecolor=bg)
    plt.close(fig)
    return {"top": round(float(top), 1), "bottom": round(float(bot), 1)}


def attach(chapter: str, node_id: str, png: Path, win: dict) -> str:
    course = HERE / "out" / chapter
    layer = json.loads((course / "layer.json").read_text(encoding="utf-8"))
    node = next(n for n in layer["nodes"] if n["id"] == node_id)
    ill = {"id": node_id + ".volve", "class": "A", "src": "media/" + png.name,
           "alt": "Планшет каротажа реальной скважины Volve 15/9-19 A: ГК, сопротивление, плотностной и нейтронный каротаж, "
                  "насыщение по интерпретации Equinor; жёлтым выделены песчаники-коллекторы",
           "caption": f"Реальная скважина Volve 15/9-19 A, {win['top']:.0f}–{win['bottom']:.0f} м: в песчанике (жёлтый) ГК низкий, "
                      "сопротивление выше, кривые ГГК-П и НГК сближаются — признаки коллектора с углеводородами из этого шага",
           "provenance": "реальные данные", "redrawn_from": None, "source_url": SOURCE}
    node["illustrations"] = [i for i in node.get("illustrations", []) if i["id"] != ill["id"]] + [ill]
    (course / "layer.json").write_text(json.dumps(layer, ensure_ascii=False, indent=1), encoding="utf-8")
    sys.path.insert(0, str(HERE))
    try:
        import render as front
        front.render(layer, course)
    except ImportError:
        pass
    return node["title"]


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--lfp", required=True)
    p.add_argument("--cpi", required=True)
    p.add_argument("--chapter", default="train_latyshova")
    p.add_argument("--node", default="latyshova.terrigenous-reservoir-identification")
    a = p.parse_args()
    png = HERE / "out" / a.chapter / "media" / "volve-15-9-19a-log.png"
    win = draw(Path(a.lfp), Path(a.cpi), png)
    title = attach(a.chapter, a.node, png, win)
    print(f"кадр A: {png} ({win['top']}–{win['bottom']} м) → шаг «{title}»")
