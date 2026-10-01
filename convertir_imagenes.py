from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

import fitz  # PyMuPDF
from PIL import Image, ImageOps
from imageio_ffmpeg import get_ffmpeg_exe
from pillow_heif import register_heif_opener


SUPPORTED_IMAGE_EXTENSIONS = {
    ".heic",
    ".heif",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
    ".tif",
    ".tiff",
    ".bmp",
}

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".wav",
}

SUPPORTED_PDF_EXTENSIONS = {
    ".pdf",
}

Converter = Callable[[Path, Path], None]


@dataclass(frozen=True)
class ConversionKind:
    key: str
    label: str
    plural_label: str


@dataclass(frozen=True)
class ConversionSummary:
    output_dir: Path
    converted: int
    failed: int


@dataclass(frozen=True)
class ConversionFormat:
    key: str
    label: str
    kind: str
    input_extensions: frozenset[str]
    output_suffix: str
    converter: Converter


CONVERSION_KINDS: tuple[ConversionKind, ...] = (
    ConversionKind(key="image", label="Imagen", plural_label="imagenes"),
    ConversionKind(key="audio", label="Audio", plural_label="audios"),
    ConversionKind(key="pdf", label="PDF", plural_label="PDFs"),
)

KIND_BY_KEY = {conversion_kind.key: conversion_kind for conversion_kind in CONVERSION_KINDS}


def unique_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    candidate = output_dir / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = output_dir / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


# Sufijo de la carpeta de salida automatica segun el tipo de archivo.
OUTPUT_DIR_SUFFIX = {
    "image": "convertidas",
    "audio": "convertidos",
    "pdf": "comprimidos",
}


def default_output_dir(base_dir: Path, output_format: ConversionFormat) -> Path:
    suffix = OUTPUT_DIR_SUFFIX.get(output_format.kind, "convertidos")
    return base_dir.parent / f"{base_dir.name}_{suffix}"


def automatic_output_dirs(base_dir: Path) -> set[Path]:
    return {default_output_dir(base_dir, conversion_format) for conversion_format in CONVERSION_FORMATS}


def convert_image(source: Path, destination: Path, output_format: str) -> None:
    with Image.open(source) as image:
        image = ImageOps.exif_transpose(image)
        exif = image.info.get("exif")

        if output_format == "jpeg":
            if image.mode in ("RGBA", "LA", "P"):
                rgba = image.convert("RGBA")
                background = Image.new("RGB", rgba.size, (255, 255, 255))
                background.paste(rgba, mask=rgba.getchannel("A"))
                image = background
            else:
                image = image.convert("RGB")

            save_options = {
                "format": "JPEG",
                "quality": 100,
                "subsampling": 0,
                "optimize": True,
            }
            if exif:
                save_options["exif"] = exif
            image.save(destination, **save_options)
            return

        if output_format == "png":
            image.save(destination, format="PNG", compress_level=0)
            return

        raise ValueError(f"Formato no soportado: {output_format}")


def convert_to_png(source: Path, destination: Path) -> None:
    convert_image(source, destination, "png")


def convert_to_jpeg(source: Path, destination: Path) -> None:
    convert_image(source, destination, "jpeg")


def run_ffmpeg(source: Path, destination: Path, output_args: list[str]) -> None:
    ffmpeg = get_ffmpeg_exe()
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(source),
        "-map_metadata",
        "0",
        "-vn",
    ]
    command.extend(output_args)
    command.append(str(destination))

    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )
    if result.returncode != 0:
        error = result.stderr.strip() or result.stdout.strip() or "ffmpeg no pudo convertir el audio"
        raise RuntimeError(error)


def convert_to_wav(source: Path, destination: Path) -> None:
    run_ffmpeg(source, destination, ["-c:a", "pcm_s24le"])


def convert_to_mp3(source: Path, destination: Path) -> None:
    run_ffmpeg(source, destination, ["-c:a", "libmp3lame", "-q:a", "0"])


# Imagenes mas pequenas que esto no compensan el costo de recomprimirlas.
PDF_MIN_IMAGE_PIXELS = 4096


def recompress_pdf_image(document: "fitz.Document", page, xref: int, image_quality: int) -> None:
    original = document.xref_stream_raw(xref)
    pixmap = fitz.Pixmap(document, xref)
    try:
        if pixmap.alpha or pixmap.colorspace is None:
            return
        if pixmap.n not in (1, 3):
            pixmap = fitz.Pixmap(fitz.csRGB, pixmap)
        if pixmap.width * pixmap.height < PDF_MIN_IMAGE_PIXELS:
            return
        recompressed = pixmap.tobytes("jpeg", jpg_quality=image_quality)
    finally:
        pixmap = None

    if original is not None and len(recompressed) >= len(original):
        return
    page.replace_image(xref, stream=recompressed)


def compress_pdf(source: Path, destination: Path, image_quality: int) -> None:
    document = fitz.open(source)
    try:
        processed: set[int] = set()
        for page in document:
            for image in page.get_images(full=True):
                xref, smask = image[0], image[1]
                if xref in processed:
                    continue
                processed.add(xref)
                # Las imagenes con mascara de transparencia se dejan intactas
                # para no perder el canal alfa al pasarlas a JPEG.
                if smask:
                    continue
                try:
                    recompress_pdf_image(document, page, xref, image_quality)
                except Exception:  # noqa: BLE001 - omite imagenes que no se pueden recomprimir.
                    continue

        document.save(
            destination,
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )
    finally:
        document.close()


def compress_pdf_light(source: Path, destination: Path) -> None:
    compress_pdf(source, destination, image_quality=80)


def compress_pdf_medium(source: Path, destination: Path) -> None:
    compress_pdf(source, destination, image_quality=60)


def compress_pdf_strong(source: Path, destination: Path) -> None:
    compress_pdf(source, destination, image_quality=40)


CONVERSION_FORMATS: tuple[ConversionFormat, ...] = (
    ConversionFormat(
        key="png",
        label="PNG sin perdida",
        kind="image",
        input_extensions=frozenset(SUPPORTED_IMAGE_EXTENSIONS),
        output_suffix=".png",
        converter=convert_to_png,
    ),
    ConversionFormat(
        key="jpeg",
        label="JPEG calidad maxima",
        kind="image",
        input_extensions=frozenset(SUPPORTED_IMAGE_EXTENSIONS),
        output_suffix=".jpg",
        converter=convert_to_jpeg,
    ),
    ConversionFormat(
        key="wav",
        label="WAV sin perdida adicional",
        kind="audio",
        input_extensions=frozenset(SUPPORTED_AUDIO_EXTENSIONS),
        output_suffix=".wav",
        converter=convert_to_wav,
    ),
    ConversionFormat(
        key="mp3",
        label="MP3 alta calidad",
        kind="audio",
        input_extensions=frozenset(SUPPORTED_AUDIO_EXTENSIONS),
        output_suffix=".mp3",
        converter=convert_to_mp3,
    ),
    ConversionFormat(
        key="pdf_light",
        label="Comprimir poco (mejor calidad)",
        kind="pdf",
        input_extensions=frozenset(SUPPORTED_PDF_EXTENSIONS),
        output_suffix=".pdf",
        converter=compress_pdf_light,
    ),
    ConversionFormat(
        key="pdf_medium",
        label="Comprimir medio",
        kind="pdf",
        input_extensions=frozenset(SUPPORTED_PDF_EXTENSIONS),
        output_suffix=".pdf",
        converter=compress_pdf_medium,
    ),
    ConversionFormat(
        key="pdf_strong",
        label="Comprimir mucho (menor tamano)",
        kind="pdf",
        input_extensions=frozenset(SUPPORTED_PDF_EXTENSIONS),
        output_suffix=".pdf",
        converter=compress_pdf_strong,
    ),
)

FORMAT_BY_KEY = {conversion_format.key: conversion_format for conversion_format in CONVERSION_FORMATS}
FORMATS_BY_KIND = {
    conversion_kind.key: tuple(
        conversion_format
        for conversion_format in CONVERSION_FORMATS
        if conversion_format.kind == conversion_kind.key
    )
    for conversion_kind in CONVERSION_KINDS
}


def get_output_format(format_key: str) -> ConversionFormat:
    try:
        return FORMAT_BY_KEY[format_key]
    except KeyError as exc:
        raise ValueError(f"Formato no soportado: {format_key}") from exc


def get_conversion_kind(kind_key: str) -> ConversionKind:
    try:
        return KIND_BY_KEY[kind_key]
    except KeyError as exc:
        raise ValueError(f"Tipo de conversion no soportado: {kind_key}") from exc


def get_formats_for_kind(kind_key: str) -> tuple[ConversionFormat, ...]:
    formats = FORMATS_BY_KIND.get(kind_key, ())
    if not formats:
        raise ValueError(f"No hay formatos configurados para: {kind_key}")
    return formats


class ImageConverterApp:
    def __init__(self, root: Tk) -> None:
        self.root = root
        self.root.title("Convertidor de archivos")
        self.root.geometry("720x500")
        self.root.minsize(640, 440)

        self.input_files: list[Path] = []
        self.input_summary = StringVar(value="Ningun archivo seleccionado")
        self.output_dir = StringVar()
        self.conversion_kind = StringVar(value="image")
        self.output_format = StringVar(value="png")
        self.status = StringVar(value="Selecciona los archivos para comenzar.")
        self.progress_text = StringVar(value="0 / 0")

        self.events: queue.Queue[tuple[str, object]] = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_requested = threading.Event()
        self.format_frame: ttk.Frame | None = None

        self._build_ui()
        self.conversion_kind.trace_add("write", self.on_conversion_kind_changed)
        self.output_format.trace_add("write", self.on_output_format_changed)

    def _build_ui(self) -> None:
        main = ttk.Frame(self.root, padding=16)
        main.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)
        main.columnconfigure(1, weight=1)
        main.rowconfigure(8, weight=1)

        title = ttk.Label(
            main,
            text="Convertidor de imagenes y audio",
            font=("Segoe UI", 16, "bold"),
        )
        title.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 16))

        ttk.Label(main, text="Archivos").grid(row=1, column=0, sticky="w")
        input_entry = ttk.Entry(main, textvariable=self.input_summary, state="readonly")
        input_entry.grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(main, text="Seleccionar", command=self.select_input_files).grid(
            row=1, column=2, sticky="ew"
        )

        ttk.Label(main, text="Guardar en").grid(row=2, column=0, sticky="w", pady=(10, 0))
        output_entry = ttk.Entry(main, textvariable=self.output_dir)
        output_entry.grid(row=2, column=1, sticky="ew", padx=8, pady=(10, 0))
        ttk.Button(main, text="Seleccionar", command=self.select_output_dir).grid(
            row=2, column=2, sticky="ew", pady=(10, 0)
        )

        ttk.Label(main, text="Tipo de archivo").grid(
            row=3, column=0, sticky="w", pady=(12, 0)
        )
        kind_frame = ttk.Frame(main)
        kind_frame.grid(row=3, column=1, sticky="w", padx=8, pady=(12, 0))
        for index, conversion_kind in enumerate(CONVERSION_KINDS):
            ttk.Radiobutton(
                kind_frame,
                text=conversion_kind.label,
                value=conversion_kind.key,
                variable=self.conversion_kind,
            ).grid(
                row=0,
                column=index,
                sticky="w",
                padx=(18, 0) if index else 0,
            )

        ttk.Label(main, text="Convertir a").grid(
            row=4, column=0, sticky="w", pady=(12, 0)
        )
        self.format_frame = ttk.Frame(main)
        self.format_frame.grid(row=4, column=1, sticky="w", padx=8, pady=(12, 0))
        self.rebuild_output_format_options()

        self.convert_button = ttk.Button(
            main,
            text="Convertir archivos",
            command=self.start_conversion,
        )
        self.convert_button.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(18, 8))

        self.cancel_button = ttk.Button(
            main,
            text="Cancelar",
            command=self.cancel_conversion,
            state="disabled",
        )
        self.cancel_button.grid(row=6, column=2, sticky="ew", pady=(18, 8), padx=(8, 0))

        self.progress = ttk.Progressbar(main, mode="determinate", maximum=100)
        self.progress.grid(row=7, column=0, columnspan=2, sticky="ew", pady=(4, 4))
        ttk.Label(main, textvariable=self.progress_text).grid(
            row=7, column=2, sticky="e", padx=(8, 0)
        )

        self.log = ScrolledText(main, height=12, wrap="word", state="disabled")
        self.log.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(10, 8))

        ttk.Label(main, textvariable=self.status).grid(
            row=9, column=0, columnspan=3, sticky="w"
        )

    def rebuild_output_format_options(self) -> None:
        if self.format_frame is None:
            return

        for child in self.format_frame.winfo_children():
            child.destroy()

        formats = get_formats_for_kind(self.conversion_kind.get())
        if self.output_format.get() not in {conversion_format.key for conversion_format in formats}:
            self.output_format.set(formats[0].key)

        for index, conversion_format in enumerate(formats):
            ttk.Radiobutton(
                self.format_frame,
                text=conversion_format.label,
                value=conversion_format.key,
                variable=self.output_format,
            ).grid(
                row=0,
                column=index,
                sticky="w",
                padx=(18, 0) if index else 0,
            )

    def on_conversion_kind_changed(self, *_args: object) -> None:
        self.rebuild_output_format_options()
        # Al cambiar de tipo los archivos elegidos dejan de ser validos.
        self.clear_input_files()
        self.update_default_output_dir()

    def on_output_format_changed(self, *_args: object) -> None:
        self.update_default_output_dir()

    def input_base_dir(self) -> Path | None:
        if not self.input_files:
            return None
        return self.input_files[0].parent

    def update_default_output_dir(self) -> None:
        base_dir = self.input_base_dir()
        if base_dir is None:
            return

        if not self.should_update_output_dir(base_dir):
            return

        output_format = get_output_format(self.output_format.get())
        self.output_dir.set(str(default_output_dir(base_dir, output_format)))

    def should_update_output_dir(self, base_dir: Path) -> bool:
        raw_output = self.output_dir.get().strip()
        if not raw_output:
            return True

        output_dir = Path(raw_output)
        return output_dir in automatic_output_dirs(base_dir)

    def current_filetypes(self) -> list[tuple[str, str]]:
        output_format = get_output_format(self.output_format.get())
        output_kind = get_conversion_kind(output_format.kind)
        patterns = " ".join(f"*{extension}" for extension in sorted(output_format.input_extensions))
        return [
            (f"Archivos de {output_kind.label.lower()}", patterns),
            ("Todos los archivos", "*.*"),
        ]

    def clear_input_files(self) -> None:
        self.input_files = []
        self.input_summary.set("Ningun archivo seleccionado")

    def select_input_files(self) -> None:
        output_format = get_output_format(self.output_format.get())
        selected = filedialog.askopenfilenames(
            title="Selecciona los archivos",
            filetypes=self.current_filetypes(),
        )
        if not selected:
            return

        files = [
            path
            for path in (Path(item) for item in selected)
            if path.suffix.lower() in output_format.input_extensions
        ]
        skipped = len(selected) - len(files)

        self.input_files = files
        if files:
            summary = f"{len(files)} archivo(s) seleccionado(s)"
            if skipped:
                summary += f" ({skipped} omitido(s) por formato)"
            self.input_summary.set(summary)
        else:
            self.input_summary.set("Ningun archivo compatible seleccionado")

        self.update_default_output_dir()

    def select_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona donde guardar los archivos")
        if selected:
            self.output_dir.set(selected)

    def start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        if not self.input_files:
            messagebox.showwarning("Faltan archivos", "Selecciona al menos un archivo.")
            return

        output_format = get_output_format(self.output_format.get())
        files = [
            path.resolve()
            for path in self.input_files
            if path.suffix.lower() in output_format.input_extensions
        ]
        if not files:
            messagebox.showwarning(
                "Sin archivos compatibles",
                "Los archivos seleccionados no coinciden con el formato elegido.",
            )
            return

        raw_output = self.output_dir.get().strip()
        if raw_output:
            output_dir = Path(raw_output).resolve()
        else:
            output_dir = default_output_dir(files[0].parent, output_format)

        self.clear_log()
        self.progress["value"] = 0
        self.progress_text.set("0 / 0")
        output_kind = get_conversion_kind(output_format.kind)
        self.status.set(f"Procesando {output_kind.plural_label}...")
        self.cancel_requested.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker = threading.Thread(
            target=self.run_conversion,
            args=(files, output_dir, output_format),
            daemon=True,
        )
        self.worker.start()
        self.root.after(100, self.process_events)

    def cancel_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            self.cancel_requested.set()
            self.cancel_button.configure(state="disabled")
            self.status.set("Cancelando conversion...")

    def run_conversion(
        self,
        files: list[Path],
        output_dir: Path,
        output_format: ConversionFormat,
    ) -> None:
        suffix = output_format.output_suffix

        if not files:
            self.events.put(("empty", None))
            return

        output_dir.mkdir(parents=True, exist_ok=True)
        self.events.put(("total", len(files)))

        converted = 0
        failed = 0
        cancelled = False

        for index, source in enumerate(files, start=1):
            if self.cancel_requested.is_set():
                cancelled = True
                break

            destination = unique_output_path(output_dir, source.stem, suffix)

            try:
                output_format.converter(source, destination)
                converted += 1
                self.events.put(("log", f"OK  {source.name} -> {destination}"))
            except Exception as exc:  # noqa: BLE001 - keep converting the rest.
                failed += 1
                self.events.put(("log", f"ERR {source}: {exc}"))

            self.events.put(("progress", (index, len(files))))

        if cancelled:
            self.events.put(
                (
                    "cancelled",
                    ConversionSummary(
                        output_dir=output_dir,
                        converted=converted,
                        failed=failed,
                    ),
                )
            )
            return

        self.events.put(
            (
                "done",
                ConversionSummary(output_dir=output_dir, converted=converted, failed=failed),
            )
        )

    def process_events(self) -> None:
        while True:
            try:
                event, payload = self.events.get_nowait()
            except queue.Empty:
                break

            if event == "total":
                total = int(payload)
                self.progress.configure(maximum=total)
                self.progress["value"] = 0
                self.progress_text.set(f"0 / {total}")
                output_format = get_output_format(self.output_format.get())
                output_kind = get_conversion_kind(output_format.kind)
                self.status.set(f"Procesando {output_kind.plural_label}...")
            elif event == "progress":
                current, total = payload  # type: ignore[misc]
                self.progress["value"] = current
                self.progress_text.set(f"{current} / {total}")
            elif event == "log":
                self.append_log(str(payload))
            elif event == "empty":
                self.convert_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.status.set("No hay archivos para procesar.")
                messagebox.showinfo(
                    "Sin archivos",
                    "No hay archivos compatibles para procesar.",
                )
            elif event == "done":
                summary = payload
                if isinstance(summary, ConversionSummary):
                    self.convert_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.status.set(f"Terminado. Carpeta de salida: {summary.output_dir}")
                    messagebox.showinfo(
                        "Conversion finalizada",
                        (
                            f"Archivos convertidos: {summary.converted}\n"
                            f"Errores: {summary.failed}\n\n"
                            f"Carpeta de salida:\n{summary.output_dir}"
                        ),
                    )
            elif event == "cancelled":
                summary = payload
                if isinstance(summary, ConversionSummary):
                    self.convert_button.configure(state="normal")
                    self.cancel_button.configure(state="disabled")
                    self.status.set(
                        f"Cancelado. Archivos convertidos: {summary.converted}. "
                        f"Carpeta de salida: {summary.output_dir}"
                    )
                    messagebox.showinfo(
                        "Conversion cancelada",
                        (
                            f"Archivos convertidos antes de cancelar: {summary.converted}\n"
                            f"Errores: {summary.failed}\n\n"
                            f"Carpeta de salida:\n{summary.output_dir}"
                        ),
                    )

        if self.worker and self.worker.is_alive():
            self.root.after(100, self.process_events)

    def append_log(self, text: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", f"{text}\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self) -> None:
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")


def main() -> None:
    register_heif_opener()
    root = Tk()
    app = ImageConverterApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
