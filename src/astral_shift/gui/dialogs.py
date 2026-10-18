"""The interactive actions. Each dialog collects parameters and returns a
callable that does the work off the UI thread."""
from __future__ import annotations

from functools import partial
from pathlib import Path
from typing import Callable

from PIL import Image
from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QImage
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QDialog, QGridLayout, QHBoxLayout, QHeaderView, QInputDialog,
    QLabel, QListWidget, QListWidgetItem, QPushButton, QSlider, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from .. import ops
from . import icons
from .canvas import Document, PageCanvas, pil_to_qimage
from .glass import GlassDialog

Job = Callable[[], list[Path]]


def _row(*widgets, stretch_at: int | None = None) -> QHBoxLayout:
    row = QHBoxLayout()
    row.setSpacing(6)
    for i, w in enumerate(widgets):
        if w is None:
            row.addStretch(1)
        elif isinstance(w, QHBoxLayout):
            row.addLayout(w)
        else:
            row.addWidget(w)
    return row


def _chips(labels: list[str], checked: int = 0) -> tuple[QHBoxLayout, QButtonGroup, list[QPushButton]]:
    row = QHBoxLayout()
    row.setSpacing(4)
    group = QButtonGroup()
    group.setExclusive(True)
    buttons = []
    for i, label in enumerate(labels):
        b = QPushButton(label)
        b.setObjectName("Chip")
        b.setCheckable(True)
        b.setChecked(i == checked)
        group.addButton(b, i)
        row.addWidget(b)
        buttons.append(b)
    return row, group, buttons


def _slider(lo: int, hi: int, value: int) -> QSlider:
    s = QSlider(Qt.Orientation.Horizontal)
    s.setRange(lo, hi)
    s.setValue(value)
    s.setMinimumWidth(180)
    return s


class Base(GlassDialog):
    title = ""

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(self.title, parent)
        self.path = Path(path)
        self.job: Job | None = None
        self.setWindowTitle(f"{self.title}: {self.path.name}")

    def footer(self, primary: str, on_primary, reset=None) -> QPushButton:
        go = QPushButton(primary)
        go.setObjectName("Primary")
        go.clicked.connect(on_primary)
        go.setDefault(True)
        widgets = []
        if reset:
            r = QPushButton("Reset")
            r.clicked.connect(reset)
            widgets.append(r)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        widgets += [cancel, None, go]
        self.layout_.addLayout(_row(*widgets))
        return go

    def done_with(self, job: Job) -> None:
        self.job = job
        self.accept()


class PagedDialog(Base):
    """Preview with page navigation for PDFs."""

    mode = "draw"

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        self.doc = Document(self.path)
        self.page = 0
        self.canvas = PageCanvas(self.mode)
        self.per_page: dict[int, list] = {}
        self.layout_.addWidget(self.canvas, 1)
        self.prev = QPushButton("‹")
        self.next = QPushButton("›")
        self.page_label = QLabel()
        self.page_label.setObjectName("Muted")
        self.prev.clicked.connect(lambda: self.go(self.page - 1))
        self.next.clicked.connect(lambda: self.go(self.page + 1))
        self.nav = _row(None, self.prev, self.page_label, self.next, None)
        if self.doc.count > 1:
            self.layout_.addLayout(self.nav)
        else:
            for w in (self.prev, self.next, self.page_label):
                w.hide()
        self.go(0)
        self.resize(720, 820)

    def _items(self) -> list:
        return self.canvas.marks if self.mode == "draw" else self.canvas.boxes

    def go(self, i: int) -> None:
        if not 0 <= i < self.doc.count:
            return
        self.per_page[self.page] = list(self._items())
        self.page = i
        items = list(self.per_page.get(i, []))
        if self.mode == "draw":
            self.canvas.marks = items
        else:
            self.canvas.boxes = items
        self.canvas.set_image(self.doc.page(i))
        self.page_label.setText(f"Page {i + 1} of {self.doc.count}")
        self.prev.setEnabled(i > 0)
        self.next.setEnabled(i < self.doc.count - 1)

    def collected(self) -> dict[int, list]:
        self.per_page[self.page] = list(self._items())
        return {k: v for k, v in self.per_page.items() if v}


# --- crop -------------------------------------------------------------------------

class CropDialog(Base):
    title = "Crop Image"
    RATIOS = [("Free", None), ("1:1", 1.0), ("16:9", 16 / 9), ("9:16", 9 / 16), ("4:3", 4 / 3), ("3:4", 3 / 4)]

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        if ops.kind(self.path) == "pdf":
            self.title_label.setText("Crop PDF")
        self.doc = Document(self.path)
        self.canvas = PageCanvas("crop")
        self.canvas.set_image(self.doc.page(0))
        self.layout_.addWidget(self.canvas, 1)
        chips, self.ratio_group, _ = _chips([r[0] for r in self.RATIOS])
        self.ratio_group.idClicked.connect(lambda i: self.canvas.set_aspect(self.RATIOS[i][1]))
        label = QLabel("Aspect ratio")
        label.setObjectName("Muted")
        self.layout_.addLayout(_row(label, chips, None))
        self.size_label = QLabel()
        self.size_label.setObjectName("Muted")
        self.layout_.addWidget(self.size_label)
        self.canvas.changed.connect(self._update_size)
        self._update_size()
        self.footer("Apply", self._apply, reset=self._reset)
        self.resize(640, 760)

    def _update_size(self) -> None:
        real_w, real_h = self.doc.sizes[0]
        w = round(self.canvas.crop.width() * real_w)
        h = round(self.canvas.crop.height() * real_h)
        unit = "pt" if self.doc.kind == "pdf" else "px"
        self.size_label.setText(f"W {w}  H {h} {unit}" + ("   (applies to every page)" if self.doc.count > 1 else ""))

    def _reset(self) -> None:
        self.ratio_group.button(0).setChecked(True)
        self.canvas.set_aspect(None)

    def _apply(self) -> None:
        r = self.canvas.crop
        rect = (r.left(), r.top(), r.right(), r.bottom())
        self.done_with(lambda: [ops.crop(self.path, rect)])


# --- background -------------------------------------------------------------------

class BackgroundDialog(Base):
    title = "Add BG"

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        src = ops.first_page_image(self.path, dpi=110)
        src.thumbnail((700, 700))
        self.src = src
        self.bg = ops.Background()
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(480, 340)
        self.layout_.addWidget(self.preview, 1)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        swatches = QHBoxLayout()
        swatches.setSpacing(5)
        self.swatch_group = QButtonGroup(self)
        for i, (name, (a, b)) in enumerate(ops.PRESETS.items()):
            btn = QPushButton()
            btn.setObjectName("Swatch")
            btn.setCheckable(True)
            btn.setToolTip(name.title())
            btn.setStyleSheet(
                f"QPushButton#Swatch {{ background: qlineargradient(x1:0,y1:0,x2:1,y2:1,"
                f"stop:0 rgb{a}, stop:1 rgb{b}); }}")
            btn.setChecked(i == 0)
            self.swatch_group.addButton(btn, i)
            swatches.addWidget(btn)
        swatches.addStretch(1)
        self.swatch_group.idClicked.connect(self._pick_preset)
        self._labels = {}
        grid.addWidget(QLabel("Background"), 0, 0)
        grid.addLayout(swatches, 0, 1, 1, 2)
        self.padding = _slider(0, 40, 12)
        self.corners = _slider(0, 20, 3)
        self.shadow = _slider(0, 100, 50)
        for row, (name, s, fmt) in enumerate(
            [("Padding", self.padding, "{}%"), ("Corners", self.corners, "{}%"), ("Shadow", self.shadow, "{}%")], 1
        ):
            grid.addWidget(QLabel(name), row, 0)
            grid.addWidget(s, row, 1)
            value = QLabel(fmt.format(s.value()))
            value.setObjectName("Muted")
            value.setMinimumWidth(40)
            self._labels[name] = (value, fmt)
            grid.addWidget(value, row, 2)
            s.valueChanged.connect(partial(self._slid, name))
        chips, self.ratio_group, _ = _chips(list(ops.RATIOS))
        self.ratio_group.idClicked.connect(lambda _i: self._schedule())
        grid.addWidget(QLabel("Ratio"), 4, 0)
        grid.addLayout(_row(chips, None), 4, 1, 1, 2)
        self.layout_.addLayout(grid)
        self.footer("Save with Background", self._apply, reset=self._reset)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(60)
        self._timer.timeout.connect(self._render)
        self._render()
        self.resize(640, 720)

    def _slid(self, name: str, v: int) -> None:
        label, fmt = self._labels[name]
        label.setText(fmt.format(v))
        self._schedule()

    def _pick_preset(self, i: int) -> None:
        self._schedule()

    def _schedule(self) -> None:
        self._timer.start()

    def _current(self) -> ops.Background:
        preset = list(ops.PRESETS.values())[max(0, self.swatch_group.checkedId())]
        ratio = list(ops.RATIOS)[max(0, self.ratio_group.checkedId())]
        return ops.Background(preset, self.padding.value() / 100, self.corners.value() / 100,
                              self.shadow.value() / 100, ratio)

    def _render(self) -> None:
        from ..ops.background import compose
        out = compose(self.src, self._current())
        img = pil_to_qimage(out)
        box = self.preview.size()
        from PySide6.QtGui import QPixmap
        pm = QPixmap.fromImage(img).scaled(box, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._schedule()

    def _reset(self) -> None:
        self.swatch_group.button(0).setChecked(True)
        self.ratio_group.button(0).setChecked(True)
        self.padding.setValue(12)
        self.corners.setValue(3)
        self.shadow.setValue(50)
        self._schedule()

    def _apply(self) -> None:
        bg = self._current()
        self.done_with(lambda: [ops.add_background(self.path, bg)])


# --- redact -------------------------------------------------------------------------

class RedactDialog(PagedDialog):
    title = "Redact"
    mode = "boxes"

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        hint = QLabel("Drag over anything to hide it." + (" Text under the boxes is removed from the PDF."
                                                          if self.doc.kind == "pdf" else ""))
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.layout_.insertWidget(1, hint)
        undo = QPushButton(icons.icon("undo"), " Undo")
        undo.clicked.connect(self.canvas.undo)
        self.layout_.addLayout(_row(undo, None))
        self.go_btn = self.footer("Redact", self._apply)
        self.canvas.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.go_btn.setEnabled(bool(self.collected()))

    def go(self, i: int) -> None:
        super().go(i)
        if hasattr(self, "go_btn"):
            self._refresh()

    def _apply(self) -> None:
        boxes = {k: [(r.left(), r.top(), r.right(), r.bottom()) for r in v] for k, v in self.collected().items()}
        self.done_with(lambda: [ops.redact(self.path, boxes)])


# --- annotate -----------------------------------------------------------------------

class AnnotateDialog(PagedDialog):
    title = "Annotate"
    mode = "draw"
    COLORS = [(255, 59, 48), (255, 149, 0), (255, 214, 10), (52, 199, 89), (0, 122, 255), (175, 82, 222), (0, 0, 0), (255, 255, 255)]
    TOOLS = [("pen", "Pen"), ("highlight", "Highlight"), ("rect", "Box"), ("arrow", "Arrow"), ("text", "Text")]

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        tools = QHBoxLayout()
        tools.setSpacing(4)
        self.tool_group = QButtonGroup(self)
        for i, (key, label) in enumerate(self.TOOLS):
            b = QPushButton(icons.icon(key), f" {label}")
            b.setObjectName("Chip")
            b.setCheckable(True)
            b.setChecked(i == 0)
            self.tool_group.addButton(b, i)
            tools.addWidget(b)
        self.tool_group.idClicked.connect(lambda i: setattr(self.canvas, "tool", self.TOOLS[i][0]))
        colors = QHBoxLayout()
        colors.setSpacing(4)
        self.color_group = QButtonGroup(self)
        for i, c in enumerate(self.COLORS):
            b = QPushButton()
            b.setObjectName("Swatch")
            b.setCheckable(True)
            b.setChecked(i == 0)
            b.setStyleSheet(f"QPushButton#Swatch {{ background: rgb{c}; min-width: 20px; max-width: 20px; min-height: 20px; max-height: 20px; border-radius: 10px; }}")
            self.color_group.addButton(b, i)
            colors.addWidget(b)
        self.color_group.idClicked.connect(lambda i: setattr(self.canvas, "color", self.COLORS[i]))
        self.layout_.insertLayout(1, _row(tools, None, colors))
        undo = QPushButton(icons.icon("undo"), " Undo")
        undo.clicked.connect(self.canvas.undo)
        self.layout_.addLayout(_row(undo, None))
        self.canvas.text_requested.connect(self._add_text)
        self.go_btn = self.footer("Save", self._apply)
        self.canvas.changed.connect(self._refresh)
        self._refresh()

    def _refresh(self) -> None:
        self.go_btn.setEnabled(bool(self.collected()))

    def go(self, i: int) -> None:
        super().go(i)
        if hasattr(self, "go_btn"):
            self._refresh()

    def _add_text(self, n: QPointF) -> None:
        text, ok = QInputDialog.getText(self, "Text", "Text:")
        if ok and text.strip():
            self.canvas.marks.append(ops.Mark("text", [(n.x(), n.y())], color=self.canvas.color, text=text.strip()))
            self.canvas.changed.emit()
            self.canvas.update()

    def _apply(self) -> None:
        marks = self.collected()
        self.done_with(lambda: [ops.annotate(self.path, marks)])


# --- edit -----------------------------------------------------------------------------

class EditDialog(Base):
    title = "Edit"

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        self.is_pdf = ops.kind(self.path) == "pdf"
        self.adj = ops.Adjustments()
        src = ops.first_page_image(self.path, dpi=100)
        src.thumbnail((640, 640))
        self.src = src
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(420, 340)
        self.layout_.addWidget(self.preview, 1)

        rot_l = QPushButton(icons.icon("rotate"), " Rotate")
        rot_l.clicked.connect(lambda: self._set(rotate=(self.adj.rotate + 90) % 360))
        flip_h = QPushButton(icons.icon("flip_h"), " Flip H")
        flip_h.clicked.connect(lambda: self._set(flip_h=not self.adj.flip_h))
        flip_v = QPushButton(icons.icon("flip_v"), " Flip V")
        flip_v.clicked.connect(lambda: self._set(flip_v=not self.adj.flip_v))
        self.layout_.addLayout(_row(None, rot_l, flip_h, flip_v, None))

        grid = QGridLayout()
        self.sliders: dict[str, QSlider] = {}
        for row, (key, label, lo, hi, val) in enumerate([
            ("scale", "Size", 10, 200, 100),
            ("brightness", "Brightness", 20, 200, 100),
            ("contrast", "Contrast", 20, 200, 100),
            ("saturation", "Saturation", 0, 200, 100),
        ]):
            s = _slider(lo, hi, val)
            value = QLabel(f"{val}%")
            value.setObjectName("Muted")
            value.setMinimumWidth(44)
            s.valueChanged.connect(lambda v, k=key, l=value: (l.setText(f"{v}%"), self._set(**{k: v / 100})))
            grid.addWidget(QLabel(label), row, 0)
            grid.addWidget(s, row, 1)
            grid.addWidget(value, row, 2)
            self.sliders[key] = s
        self.gray = QCheckBox("Black and white")
        self.gray.toggled.connect(lambda v: self._set(grayscale=v))
        grid.addWidget(self.gray, 4, 1)
        holder = QWidget()
        holder.setLayout(grid)
        holder.setStyleSheet("background: transparent;")
        self.layout_.addWidget(holder)
        if self.is_pdf:
            holder.setEnabled(False)
            flip_h.setEnabled(False)
            flip_v.setEnabled(False)
            note = QLabel("PDF pages stay sharp: only rotation applies to PDFs.")
            note.setObjectName("Muted")
            self.layout_.addWidget(note)
            self.split_btn = QPushButton("Split into Pages")
            self.split_btn.clicked.connect(lambda: self.done_with(lambda: ops.split(self.path)))
            self.split_btn.setEnabled(Document(self.path).count > 1)
            self.layout_.addLayout(_row(None, self.split_btn, None))
        self.footer("Save", self._apply, reset=self._reset)
        self._render()
        self.resize(600, 700)

    def _set(self, **kw) -> None:
        for k, v in kw.items():
            setattr(self.adj, k, v)
        self._render()

    def _render(self) -> None:
        from ..ops.edit import apply_adjustments, Adjustments
        preview_adj = Adjustments(**{**self.adj.__dict__, "scale": 1.0})
        img = pil_to_qimage(apply_adjustments(self.src, preview_adj))
        from PySide6.QtGui import QPixmap
        pm = QPixmap.fromImage(img).scaled(self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                            Qt.TransformationMode.SmoothTransformation)
        self.preview.setPixmap(pm)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self._render()

    def _reset(self) -> None:
        self.adj = ops.Adjustments()
        for k, s in self.sliders.items():
            s.blockSignals(True)
            s.setValue(100)
            s.blockSignals(False)
        self.gray.setChecked(False)
        self._render()

    def _apply(self) -> None:
        adj = ops.Adjustments(**self.adj.__dict__)
        self.done_with(lambda: [ops.edit(self.path, adj)])


# --- metadata ---------------------------------------------------------------------------

class MetadataDialog(Base):
    title = "Metadata"

    def __init__(self, path: Path, parent: QWidget | None = None) -> None:
        super().__init__(path, parent)
        meta = ops.read_metadata(self.path)
        table = QTableWidget(len(meta), 2)
        table.setHorizontalHeaderLabels(["Field", "Value"])
        table.verticalHeader().hide()
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        for i, (k, v) in enumerate(meta.items()):
            table.setItem(i, 0, QTableWidgetItem(k))
            table.setItem(i, 1, QTableWidgetItem(v))
        self.layout_.addWidget(table, 1)
        note = QLabel("Saving a clean copy removes author, software, GPS, dates and XMP. The original is kept.")
        note.setObjectName("Muted")
        note.setWordWrap(True)
        self.layout_.addWidget(note)
        self.footer("Save Clean Copy", lambda: self.done_with(lambda: [ops.strip_metadata(self.path)]))
        self.resize(560, 520)


# --- merge ---------------------------------------------------------------------------------

class MergeDialog(GlassDialog):
    """Order the dropped files, then join them into one PDF."""

    def __init__(self, files: list[Path], parent: QWidget | None = None) -> None:
        super().__init__("Merge into PDF", parent)
        self.files = [Path(f) for f in files]
        self.job: Job | None = None
        hint = QLabel("Drag to reorder. PDFs and images become one PDF, in this order.")
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        self.layout_.addWidget(hint)
        self.list = QListWidget()
        self.list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.list.setMinimumSize(380, 260)
        for f in self.files:
            item = QListWidgetItem(icons.icon("file" if ops.kind(f) == "pdf" else "background"), f.name)
            item.setData(0x0100, str(f))  # Qt.UserRole
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.layout_.addWidget(self.list, 1)
        up = QPushButton("Move Up")
        up.clicked.connect(lambda: self._move(-1))
        down = QPushButton("Move Down")
        down.clicked.connect(lambda: self._move(1))
        self.layout_.addLayout(_row(up, down, None))
        go = QPushButton("Merge")
        go.setObjectName("Primary")
        go.clicked.connect(self._apply)
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        self.layout_.addLayout(_row(cancel, None, go))
        self.resize(460, 460)

    def ordered(self) -> list[Path]:
        return [Path(self.list.item(i).data(0x0100)) for i in range(self.list.count())]

    def _move(self, step: int) -> None:
        row = self.list.currentRow()
        to = row + step
        if 0 <= to < self.list.count():
            item = self.list.takeItem(row)
            self.list.insertItem(to, item)
            self.list.setCurrentRow(to)

    def _apply(self) -> None:
        files = self.ordered()
        self.job = lambda: [ops.merge(files)]
        self.accept()


DIALOGS = {
    "crop": CropDialog,
    "background": BackgroundDialog,
    "redact": RedactDialog,
    "annotate": AnnotateDialog,
    "edit": EditDialog,
    "metadata": MetadataDialog,
}
