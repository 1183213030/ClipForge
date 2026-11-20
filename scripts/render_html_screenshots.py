import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

from PySide6.QtCore import QUrl, QTimer
from PySide6.QtWidgets import QApplication
from PySide6.QtWebEngineWidgets import QWebEngineView

def render_html_screenshots():
    app = QApplication.instance() or QApplication(sys.argv)
    
    html_file = (PROJECT_ROOT / "docs" / "ui_proposal" / "clipforge_awwwards_concept.html").resolve()
    out_dir = PROJECT_ROOT / "docs" / "ui_screenshots"
    artifact_dir = Path(r"C:\Users\123\.gemini\antigravity\brain\7aa825f9-f09c-4552-acbd-1c1d088ad80b\screenshots")

    view = QWebEngineView()
    view.resize(1440, 920)
    view.load(QUrl.fromLocalFile(str(html_file)))
    view.show()

    def on_loaded(ok):
        if not ok:
            print("Failed to load HTML")
            app.quit()
            return
        
        # 1. Grab Page 0 (Batch Mix)
        QTimer.singleShot(1000, capture_batch)

    def capture_batch():
        p0 = view.grab()
        p0.save(str(out_dir / "concept_batch_mix.png"))
        p0.save(str(artifact_dir / "concept_batch_mix.png"))
        print("Captured concept_batch_mix.png")

        # 2. Switch to Workbench
        view.page().runJavaScript("switchTab('workbench');")
        QTimer.singleShot(600, capture_workbench)

    def capture_workbench():
        p1 = view.grab()
        p1.save(str(out_dir / "concept_workbench.png"))
        p1.save(str(artifact_dir / "concept_workbench.png"))
        print("Captured concept_workbench.png")
        app.quit()

    view.loadFinished.connect(on_loaded)
    app.exec()

if __name__ == "__main__":
    render_html_screenshots()
