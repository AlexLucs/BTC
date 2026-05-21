import os
import sys
import json
import webview
from pathlib import Path
from screeninfo import get_monitors
import pygetwindow as gw
import configparser
import win32gui
import win32con

# Constantes
WINDOW_TITLE = "BTC Status"
WINDOW_WIDTH = 500
WINDOW_HEIGHT = 810


class ExposedApi:
    """API exposta para comunicação Javascript <-> Python."""

    def fechar(self):
        """Fecha a janela."""
        global window
        if window:
            window.destroy()

    def minimizar(self):
        """Minimiza a janela."""
        global window
        if window:
            window.minimize()

    def centralizar(self, move=False):
        """Centraliza a janela na tela.

        O argumento `move` é recebido do JS como booleano (true/false).
        Quando move=True, move a janela para a posição centralizada;
        caso contrário, apenas retorna as coordenadas.
        """
        global window
        monitors = get_monitors()

        if move:
            windows = gw.getWindowsWithTitle(WINDOW_TITLE)
            if windows:
                window1 = windows[0]
                x_position1 = window1.left
                y_position1 = window1.top
                monitor = monitors[1] if x_position1 <= -1 and len(monitors) > 1 else monitors[0]
                x_position, y_position = self._centrar_posicao(monitor)
            else:
                x_position, y_position = 0, 0

            window.move(x_position, y_position)
        else:
            monitor = monitors[0] if monitors else None
            return self._centrar_posicao(monitor)

    def _centrar_posicao(self, monitor):
        """Calcula a posição centralizada para um monitor."""
        if not monitor:
            return 0, 0
        x_position = monitor.x + (monitor.width - WINDOW_WIDTH) // 2
        y_position = monitor.y + (monitor.height - WINDOW_HEIGHT) // 2
        return x_position, y_position

    def fixarTopo(self):
        """Alterna fixação da janela no topo."""
        hwnd = win32gui.GetForegroundWindow()
        estilo = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if estilo & win32con.WS_EX_TOPMOST:
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE, estilo & ~win32con.WS_EX_TOPMOST
            )
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_NOTOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )
        else:
            win32gui.SetWindowLong(
                hwnd, win32con.GWL_EXSTYLE, estilo | win32con.WS_EX_TOPMOST
            )
            win32gui.SetWindowPos(
                hwnd, win32con.HWND_TOPMOST, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
            )

    def salvar_alerta(self, alerta):
        """Salva alertas em um arquivo JSON."""
        pasta_alertas = Path(os.getenv("APPDATA")) / "btcstatus"
        pasta_alertas.mkdir(parents=True, exist_ok=True)

        arquivo_json = pasta_alertas / "Alertas.json"
        try:
            with open(arquivo_json, "w", encoding="utf-8") as file:
                json.dump(alerta, file, indent=4)
        except (OSError, ValueError) as e:
            print(f"Erro ao salvar alerta: {e}")

    def carregar_alerta(self):
        """Carrega alertas de um arquivo JSON."""
        arquivo_json = Path(os.getenv("APPDATA")) / "btcstatus" / "Alertas.json"

        if not arquivo_json.is_file():
            return []

        try:
            with open(arquivo_json, "r", encoding="utf-8") as file:
                return json.load(file)
        except (json.JSONDecodeError, OSError) as e:
            print(f"Erro ao carregar o arquivo JSON: {e}")
            return []


def salvar_janela():
    """Salva a posição da janela em um arquivo de configuração."""
    windows = gw.getWindowsWithTitle(WINDOW_TITLE)
    if not windows:
        return

    try:
        window1 = windows[0]
        config_dir = Path(os.getenv("APPDATA")) / "btcstatus"
        config_dir.mkdir(parents=True, exist_ok=True)
        config_file = config_dir / "BTC Monitor.ini"

        config = configparser.ConfigParser()
        config["Position"] = {"x": str(window1.left), "y": str(window1.top)}

        with open(config_file, "w") as configfile:
            config.write(configfile)
    except Exception as e:
        print(f"Erro ao salvar posição: {e}")


def cordenadas_validas(x, y):
    """Verifica se as coordenadas estão dentro de algum monitor."""
    return any(
        monitor.x <= x <= monitor.x + monitor.width
        and monitor.y <= y <= monitor.y + monitor.height
        for monitor in get_monitors()
    )


def posicao_janela():
    """Carrega a posição da janela do arquivo de configuração."""
    config_file = Path(os.getenv("APPDATA")) / "btcstatus" / "BTC Monitor.ini"

    if not config_file.exists():
        return 0, 0

    config = configparser.ConfigParser()
    try:
        config.read(config_file)
        x_position = int(config["Position"]["x"])
        y_position = int(config["Position"]["y"])
        if cordenadas_validas(x_position, y_position):
            return x_position, y_position
    except Exception as e:
        print(f"Erro ao carregar posição da janela: {e}")

    return 0, 0


def abrir_janela():
    """Abre a janela principal do aplicativo."""
    global window
    try:
        if getattr(sys, "frozen", False):
            url = os.path.join(sys._MEIPASS, "index.html")
        else:
            url = os.path.join(os.path.dirname(__file__), "index.html")
            if not os.path.exists(url):
                url = os.path.join(
                    os.environ.get("USERPROFILE", ""),
                    "Downloads", "Bot", "btcstatus", "index.html"
                )
            if not os.path.exists(url):
                url = "index.html"

        x_position, y_position = posicao_janela()

        if x_position == 0 and y_position == 0:
            api_instance = ExposedApi()
            monitors = get_monitors()
            x_position, y_position = api_instance._centrar_posicao(monitors[0] if monitors else None)

        window = webview.create_window(
            WINDOW_TITLE,
            url,
            width=WINDOW_WIDTH,
            height=WINDOW_HEIGHT,
            frameless=True,
            background_color="#000000",
            x=x_position,
            y=y_position,
            js_api=ExposedApi(),
        )

        window.events.closing += salvar_janela

        webview.start(user_agent="pywebview")

    except Exception as e:
        print(f"Erro ao tentar abrir: {e}")


if __name__ == "__main__":
    abrir_janela()
