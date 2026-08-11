"""
Organizador do projeto — monta a estrutura de pastas a partir dos arquivos soltos.

Uso:
    1. Baixe todos os arquivos do projeto para uma pasta qualquer
    2. Coloque este script na mesma pasta
    3. Rode:  python setup_projeto.py

O script cria as subpastas corretas, move cada arquivo para o seu lugar,
gera o src/__init__.py e valida o resultado. É idempotente: rodar duas
vezes não quebra nada.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

# --------------------------------------------------------------------------- #

DESTINOS = {
    # raiz
    "app.py": "",
    "app_repasses.py": "",
    "main.py": "",
    "setup_projeto.py": None,  # None = não mover
    "requirements.txt": "",
    "README.md": "",
    "LICENSE": "",
    ".gitignore": "",
    "CLAUDE.md": "",
    "BRIEFING-CLAUDE-CODE.md": "",
    # pacote
    "conciliacao.py": "src",
    "repasses.py": "src",
    "gerador_dados.py": "src",
    "relatorio.py": "src",
    # testes
    "test_conciliacao.py": "tests",
    "test_repasses.py": "tests",
}

ESPERADOS_CRITICOS = [
    "app_repasses.py",
    "requirements.txt",
    "src/conciliacao.py",
    "src/repasses.py",
    "src/gerador_dados.py",
    "src/relatorio.py",
    "tests/test_conciliacao.py",
    "tests/test_repasses.py",
]

CONTEUDO_GITIGNORE = """__pycache__/
*.py[cod]
.venv/
venv/
env/
.pytest_cache/
.DS_Store
.vscode/
.idea/
*.log

# Nunca versionar dados reais de cliente
dados/reais/
dados/entrada/
dados/cliente/
"""


def main() -> int:
    raiz = Path(__file__).resolve().parent
    print(f"Organizando projeto em: {raiz}\n")

    for pasta in ("src", "tests", "dados/exemplo", "assets"):
        (raiz / pasta).mkdir(parents=True, exist_ok=True)

    movidos, ausentes = [], []

    for nome, destino in DESTINOS.items():
        if destino is None:
            continue
        origem = raiz / nome
        alvo = raiz / destino / nome if destino else raiz / nome

        if origem.exists() and origem != alvo:
            alvo.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(origem), str(alvo))
            movidos.append(f"{nome} -> {destino or 'raiz'}/")
        elif alvo.exists():
            pass  # já está no lugar
        else:
            ausentes.append(nome)

    # src/__init__.py é obrigatório para os imports funcionarem
    init = raiz / "src" / "__init__.py"
    if not init.exists():
        init.write_text('"""Pacote de conciliação."""\n', encoding="utf-8")
        movidos.append("src/__init__.py (criado)")

    gitignore = raiz / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text(CONTEUDO_GITIGNORE, encoding="utf-8")
        movidos.append(".gitignore (criado)")

    if movidos:
        print("Arquivos organizados:")
        for m in movidos:
            print(f"  + {m}")
    else:
        print("Nada a mover — estrutura já estava correta.")

    faltando = [c for c in ESPERADOS_CRITICOS if not (raiz / c).exists()]
    print()
    if faltando:
        print("ATENCAO — arquivos criticos ausentes:")
        for f in faltando:
            print(f"  ! {f}")
        print("\nBaixe os arquivos faltantes para esta pasta e rode o script de novo.")
        return 1

    print("Estrutura completa. Todos os arquivos criticos presentes.\n")

    resposta = input("Rodar os testes agora? [S/n] ").strip().lower()
    if resposta in ("", "s", "sim", "y"):
        print()
        try:
            subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"], cwd=raiz, check=False)
        except FileNotFoundError:
            print("pytest nao encontrado. Rode antes: pip install -r requirements.txt")

    print("\nProximo passo: abra esta pasta no Claude Code e cole o prompt")
    print("que esta no arquivo BRIEFING-CLAUDE-CODE.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())
