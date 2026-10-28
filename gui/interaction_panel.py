"""Read-only transaction feedback beside the camera preview."""

from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout

from gui.i18n import tr


class InteractionPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("interactionPanel")
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        self.title = QLabel()
        self.title.setObjectName("interactionTitle")
        self.title.setWordWrap(True)
        self.hint = QLabel()
        self.hint.setObjectName("interactionHint")
        self.hint.setWordWrap(True)
        self.steps = []
        steps = QHBoxLayout()
        steps.setSpacing(6)
        for index in range(3):
            label = QLabel()
            label.setObjectName("interactionStep")
            self.steps.append(label)
            steps.addWidget(label, 1)
        layout.addWidget(self.title)
        layout.addLayout(steps)
        layout.addWidget(self.hint)

    def present(self, feedback, *, introduction=False):
        self.title.setText(tr("main.interaction_intro") if introduction else tr(feedback.title_key))
        self.hint.setText(tr("main.interaction_intro_hint") if introduction else tr(feedback.hint_key))
        semantic = "idle" if introduction else feedback.semantic_state
        self.setProperty("semantic", semantic)
        self.title.setProperty("semantic", semantic)
        for index, label in enumerate(self.steps):
            label.setText(tr(("main.step.aim", "main.step.pinch", "main.step.release")[index]))
            label.setProperty("current", not introduction and feedback.stage == index)
            label.style().unpolish(label)
            label.style().polish(label)
        for widget in (self, self.title):
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        self.setAccessibleName(self.title.text())
        self.setAccessibleDescription(self.hint.text())
