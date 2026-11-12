# -*- mode: python ; coding: utf-8 -*-
import os

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


a = Analysis(
    ['BTC_Monitor.py'],
    pathex=[],
    binaries=[],
    datas=[('index.html', '.'), ('regras.js', '.'), ('script.js', '.'), ('style.css', '.'), ('Roboto.woff2', '.'), ('btc-logo.svg', '.'), ('alerta.mp3', '.')],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=EXCLUIR,
    noarchive=False,
    optimize=1,
)
# metricas.js no pacote: o coletor real ou o substituto vazio, sempre com o nome que o
# index.html carrega. Entrada no formato TOC do PyInstaller: (destino, origem, tipo).
a.datas += [("metricas.js", "metricas.js" if MEDICAO else "metricas_desligadas.js", "DATA")]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [('O', None, 'OPTION')],
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
