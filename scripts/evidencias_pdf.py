"""Junta os prints da auditoria da YouTube API num único PDF.

Uso: uv run py scripts/evidencias_pdf.py [pasta] [--saida=arquivo.pdf]
     (padrão: evidencias/*.png → evidencias/evidencias.pdf)

- Ordem alfabética do nome do arquivo: numere os prints (01_oauth.png, 02_consent.png, ...).
- Uma página A4 por print, em retrato ou paisagem conforme a imagem, sem distorcer.
- Garante < 10 MB: se passar, baixa a resolução/qualidade e tenta de novo.
A pasta evidencias/ é gitignored (os prints podem mostrar dados da conta).
"""
import io
import sys
sys.stdout.reconfigure(encoding='utf-8')
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).parent.parent
LIMITE_BYTES = 10 * 1024 * 1024
A4_MM = (210, 297)
MARGEM_MM = 10
# (dpi da página, qualidade JPEG) — do melhor pro mais leve até caber no limite
TENTATIVAS = [(150, 85), (120, 75), (96, 65), (72, 55)]


def _pagina(img: Image.Image, dpi: int) -> Image.Image:
    """Imagem centralizada numa página A4 branca, na orientação que melhor aproveita."""
    larg_mm, alt_mm = A4_MM if img.height >= img.width else A4_MM[::-1]
    px = lambda mm: round(mm / 25.4 * dpi)  # noqa: E731
    pagina = Image.new("RGB", (px(larg_mm), px(alt_mm)), "white")
    caixa = (pagina.width - 2 * px(MARGEM_MM), pagina.height - 2 * px(MARGEM_MM))
    escala = min(caixa[0] / img.width, caixa[1] / img.height, 1.0)   # nunca amplia
    foto = img.resize((max(1, round(img.width * escala)), max(1, round(img.height * escala))),
                      Image.LANCZOS) if escala < 1 else img
    pagina.paste(foto, ((pagina.width - foto.width) // 2, (pagina.height - foto.height) // 2))
    return pagina


def _rgb(caminho: Path) -> Image.Image:
    img = Image.open(caminho)
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        fundo = Image.new("RGB", img.size, "white")
        fundo.paste(img, mask=img.getchannel("A"))
        return fundo
    return img.convert("RGB")


def gerar_pdf(pngs: list[Path], saida: Path) -> tuple[int, int]:
    """Gera o PDF e retorna (bytes, dpi usado). Falha alto se nem a versão mais leve couber."""
    imagens = [_rgb(p) for p in pngs]
    for dpi, qualidade in TENTATIVAS:
        paginas = [_pagina(img, dpi) for img in imagens]
        buf = io.BytesIO()
        paginas[0].save(buf, "PDF", save_all=True, append_images=paginas[1:],
                        resolution=dpi, quality=qualidade)
        if buf.tell() < LIMITE_BYTES:
            saida.write_bytes(buf.getvalue())
            return buf.tell(), dpi
    raise SystemExit(f"[!] Mesmo a {TENTATIVAS[-1][0]} dpi o PDF passou de 10 MB "
                     f"({buf.tell() / 1e6:.1f} MB) — divida os prints em dois PDFs.")


def main(argv: list[str]) -> int:
    pos = [a for a in argv if not a.startswith("--")]
    flags = dict(a[2:].split("=", 1) for a in argv if a.startswith("--") and "=" in a)
    pasta = Path(pos[0]) if pos else ROOT / "evidencias"
    saida = Path(flags.get("saida", pasta / "evidencias.pdf"))

    pngs = sorted((p for p in pasta.glob("*") if p.suffix.lower() == ".png"),
                  key=lambda p: p.name.lower())
    if not pngs:
        print(f"[!] Nenhum .png em {pasta} — coloque os prints lá (ex: 01_oauth.png).")
        return 1
    tamanho, dpi = gerar_pdf(pngs, saida)
    print(f"OK {len(pngs)} página(s) · {tamanho / 1e6:.1f} MB · {dpi} dpi → {saida}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
