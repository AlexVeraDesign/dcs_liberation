from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QDialog, QGridLayout, QGroupBox, QLabel, QVBoxLayout

from game import Game
from game.csar import CsarTarget, CsarSurvivor


class QCsarInfoDialog(QDialog):
    def __init__(self, parent, target: CsarTarget, game: Game) -> None:
        super().__init__(parent)
        self.target = target
        self.game = game
        self.setMinimumWidth(520)
        self.setWindowTitle(target.name)
        self.setWindowIcon(QIcon("./resources/icon.png"))
        self.init_ui()

    def init_ui(self) -> None:
        layout = QVBoxLayout()

        summary = QGroupBox("CSAR mission")
        summary_layout = QGridLayout()
        summary_layout.addWidget(QLabel("<b>Location</b>"), 0, 0)
        summary_layout.addWidget(QLabel(self.target.location_text), 0, 1)
        summary_layout.addWidget(QLabel("<b>Turns remaining</b>"), 1, 0)
        summary_layout.addWidget(
            QLabel(str(self.target.turns_remaining(self.game.turn))), 1, 1
        )
        summary_layout.addWidget(QLabel("<b>Terrain</b>"), 2, 0)
        summary_layout.addWidget(QLabel("Sea" if self.target.sea else "Land"), 2, 1)
        summary.setLayout(summary_layout)
        layout.addWidget(summary)

        pilots = QGroupBox("Pilots")
        pilots_layout = QGridLayout()
        headers = ["Pilot", "Squadron", "Aircraft", "Ejection", "Turns left"]
        for column, header in enumerate(headers):
            pilots_layout.addWidget(QLabel(f"<b>{header}</b>"), 0, column)

        for row, survivor in enumerate(self.target.survivors, start=1):
            self.add_survivor_row(pilots_layout, row, survivor)

        pilots.setLayout(pilots_layout)
        layout.addWidget(pilots)
        self.setLayout(layout)

    def add_survivor_row(
        self, layout: QGridLayout, row: int, survivor: CsarSurvivor
    ) -> None:
        ejection = "Unknown"
        if survivor.ejection_time is not None:
            ejection = survivor.ejection_time.strftime("%Y-%m-%d %H:%M")

        turns_left = "Unknown"
        if survivor.ejection_turn is not None:
            elapsed_turns = max(0, self.game.turn - survivor.ejection_turn - 1)
            turns_left = str(max(0, self.target.lifetime_turns - elapsed_turns))

        values = [
            survivor.pilot.name,
            survivor.squadron_name,
            survivor.aircraft or "Unknown",
            ejection,
            turns_left,
        ]
        for column, value in enumerate(values):
            layout.addWidget(QLabel(value), row, column)
