# NER Spatial Coverage Analyzer

A free desktop tool for event and venue technology teams. It crosses venue design drawings with the equipment demand spreadsheet (TEAP), assigns every space to the network equipment rack (NER) that serves it, counts the ports and checks the 90 m / 70 m distance limits, entirely on the user's own computer. Nothing is sent to the cloud.

**Site:** https://mbarbosa80.github.io/ner-analyzer/
**Download:** [Releases](https://github.com/mbarbosa80/ner-analyzer/releases/latest) — Windows 10/11 (64-bit) and macOS on Apple Silicon. Python comes inside the package; no administrator rights, no internet needed to install.

## What is in this repository

| Folder | What it is |
|---|---|
| `app/` | The application: Python server (FastAPI, PyMuPDF), React interface, tests, installers, manuals (`app/docs`). See [`app/README.md`](app/README.md) and [`app/CHANGELOG.md`](app/CHANGELOG.md). |
| root (`index.html`, `assets/`) | The website, served by GitHub Pages. One static page, English and Portuguese, no cookies, no trackers. Run it locally with `start-site.bat` / `start-site.command` and open http://localhost:8080. |

The installable packages are published as Release assets, not committed (GitHub refuses files over 100 MB).

## Licence and credit

Created by **Marcelo Barbosa** ([LinkedIn](https://www.linkedin.com/in/mbarbosa80/)). Free software under the [GNU AGPL-3.0](LICENSE): use it, study it, change it and share it, keeping the credit to the author — an additional term of the licence, see [`NOTICE.txt`](NOTICE.txt). The AGPL is also the licence of PyMuPDF, the library that reads the drawings. The components the application is built on keep their own licences ([`app/THIRD-PARTY-NOTICES.txt`](app/THIRD-PARTY-NOTICES.txt)).

Exceptions: the fonts in `assets/fonts/` are under the SIL Open Font License; the author's photo (`assets/img/marcelo.jpg`) is not licensed for reuse.

This is an independent project. It is not affiliated with, sponsored or endorsed by any event organiser, rights holder, federation, venue owner or employer, and it contains no document belonging to any of them.

This tool supports the design process. It does not replace engineering approval, a site survey, cable route validation or physical inspection.

---

**PT-BR:** Ferramenta gratuita para gestores de tecnologia de venues: cruza os desenhos de design da venue com a planilha de demanda de equipamentos (TEAP), define qual rack de equipamentos de rede (NER) atende cada espaço, conta os pontos e confere os limites de 90 m / 70 m, tudo no próprio computador. Criada por Marcelo Barbosa. Software livre sob a GNU AGPL-3.0, mantendo o crédito ao autor (`NOTICE.txt`). Pacotes para Windows e Mac em *Releases*; o código está em `app/` e o site na raiz.
