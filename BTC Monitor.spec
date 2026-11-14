# -*- mode: python ; coding: utf-8 -*-
import os
import sys

# Listas do que fica fora do build por não ser usado (módulos e arquivos): ver
# exclusoes_build.py, na mesma pasta deste .spec (SPECPATH é definido pelo PyInstaller).
sys.path.insert(0, SPECPATH)
from exclusoes_build import MODULOS_OBRIGATORIOS, MODULOS_SEM_USO, OTIMIZACAO_DO_BYTECODE, sem_arquivos_sem_uso

# O setuptools entra no build só porque o cffi (usado pelo pythonnet/clr_loader)
# o importa em funções de COMPILAR extensões, que o app nunca usa (o clr_loader só
# usa FFI().dlopen). Com ele no build, o runtime hook pyi_rth_setuptools faz
# "import setuptools" em toda abertura do .exe (~90-110 ms medidos).
# Para voltar ao build antigo (comparação A/B): $env:BTC_MANTER_SETUPTOOLS = "1"
MANTER_SETUPTOOLS = os.getenv("BTC_MANTER_SETUPTOOLS") == "1"
# "distutils" NÃO entra na lista: o hook do PyInstaller o redireciona e a exclusão quebra o build.
EXCLUIR = [] if MANTER_SETUPTOOLS else ["setuptools", "pkg_resources", "_distutils_hack"]
print(f"[spec] setuptools {'MANTIDO' if MANTER_SETUPTOOLS else 'EXCLUIDO'} do build")

# Medição de desempenho: fora da versão de produção (padrão). O build para medir o .exe
# (tools/medir_abertura.py --exe) é feito com: .\criar_exe_btc.ps1 -ComMedicao
# - produção: metricas.py fica fora e o metricas.js empacotado é o substituto vazio
#   (metricas_desligadas.js), com a mesma interface;
# - com medição: entram o metricas.py e o coletor real.
MEDICAO = os.getenv("BTC_BUILD_MEDICAO") == "1"
if not MEDICAO:
    EXCLUIR.append("metricas")
print(f"[spec] medicao {'INCLUIDA (build de teste)' if MEDICAO else 'REMOVIDA (producao)'}")

# Módulos que o app não usa: da biblioteca padrão (compactação, asyncio, multiprocessing,
# decimal, xml, ssl/OpenSSL, argparse, tarfile...) com as extensões .pyd deles, as
# plataformas do pywebview de outros sistemas e a parte do cffi que compila extensões.
# Vale para os dois builds (produção e medição). Sem o ssl, o app depende de
# ssl_ausente.py e de baixar_winhttp.py.
EXCLUIR += MODULOS_SEM_USO
print(f"[spec] {len(MODULOS_SEM_USO)} modulos sem uso EXCLUIDOS (exclusoes_build.py)")


a = Analysis(
    ['BTC_Monitor.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('regras.js', '.'), ('script.js', '.'), ('style.css', '.'), ('Roboto.woff2', '.'), ('btc-logo.svg', '.'), ('alerta.mp3', '.')],
    # Módulos que só o lado .NET do pythonnet importa (a análise não os enxerga).
    hiddenimports=list(MODULOS_OBRIGATORIOS),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR,
    noarchive=False,
    optimize=OTIMIZACAO_DO_BYTECODE,
)
# metricas.js no pacote: o coletor real ou o substituto vazio, sempre com o nome que o
# index.html carrega. Entrada no formato TOC do PyInstaller: (destino, origem, tipo).
a.datas += [("metricas.js", "metricas.js" if MEDICAO else "metricas_desligadas.js", "DATA")]

# Arquivos que os hooks do pywebview e do pythonnet copiam e o app nunca carrega
# (.jar do Android, .xml de documentação). Os hooks
# podem listá-los como dados ou como binários: filtra os dois.
_antes = len(a.datas) + len(a.binaries)
a.datas = sem_arquivos_sem_uso(a.datas)
a.binaries = sem_arquivos_sem_uso(a.binaries)
print(f"[spec] {_antes - len(a.datas) - len(a.binaries)} arquivos sem uso REMOVIDOS (exclusoes_build.py)")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    # Uma opção "O" por nível: o interpretador do .exe roda no mesmo nível do bytecode.
    [('O', None, 'OPTION')] * OTIMIZACAO_DO_BYTECODE,
    exclude_binaries=True,
    name='BTC Monitor',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['btc-logo.ico'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='BTC Monitor',
)
