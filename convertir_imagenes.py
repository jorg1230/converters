from __future__ import annotations

import queue
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from tkinter import BooleanVar, StringVar, Tk, filedialog, messagebox
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText
from typing import Callable

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
)

KIND_BY_KEY = {conversion_kind.key: conversion_kind for conversion_kind in CONVERSION_KINDS}


def unique_output_path(output_dir: Path, stem: str, suffix: str) -> Path:
    candidate = output_dir / f"{stem}{suffix}"
    index = 1
    while candidate.exists():
        candidate = output_dir / f"{stem}_{index}{suffix}"
        index += 1
    return candidate


def default_output_dir(input_dir: Path, output_format: ConversionFormat) -> Path:
    return input_dir.parent / f"{input_dir.name}_convertidas_{output_format.key}"


def automatic_output_dirs(input_dir: Path) -> set[Path]:
    return {default_output_dir(input_dir, conversion_format) for conversion_format in CONVERSION_FORMATS}


def iter_supported_files(
    input_dir: Path,
    recursive: bool,
    output_format: ConversionFormat,
) -> list[Path]:
    pattern = "**/*" if recursive else "*"
    return sorted(
        path
        for path in input_dir.glob(pattern)
        if path.is_file() and path.suffix.lower() in output_format.input_extensions
    )


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

        self.input_dir = StringVar()
        self.output_dir = StringVar()
        self.conversion_kind = StringVar(value="image")
        self.output_format = StringVar(value="png")
        self.recursive = BooleanVar(value=False)
        self.status = StringVar(value="Selecciona una carpeta para comenzar.")
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

        ttk.Label(main, text="Carpeta de archivos").grid(row=1, column=0, sticky="w")
        input_entry = ttk.Entry(main, textvariable=self.input_dir)
        input_entry.grid(row=1, column=1, sticky="ew", padx=8)
        ttk.Button(main, text="Seleccionar", command=self.select_input_dir).grid(
            row=1, column=2, sticky="ew"
        )

        ttk.Label(main, text="Carpeta de salida").grid(row=2, column=0, sticky="w", pady=(10, 0))
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

        ttk.Checkbutton(
            main,
            text="Incluir subcarpetas",
            variable=self.recursive,
        ).grid(row=5, column=1, sticky="w", padx=8, pady=(10, 0))

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
        self.update_default_output_dir()

    def on_output_format_changed(self, *_args: object) -> None:
        self.update_default_output_dir()

    def update_default_output_dir(self) -> None:
        raw_input = self.input_dir.get().strip()
        if not raw_input:
            return

        input_dir = Path(raw_input)
        if not self.should_update_output_dir(input_dir):
            return

        output_format = get_output_format(self.output_format.get())
        self.output_dir.set(str(default_output_dir(input_dir, output_format)))

    def should_update_output_dir(self, input_dir: Path) -> bool:
        raw_output = self.output_dir.get().strip()
        if not raw_output:
            return True

        output_dir = Path(raw_output)
        return output_dir in automatic_output_dirs(input_dir)

    def select_input_dir(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona la carpeta con archivos")
        if selected:
            self.input_dir.set(selected)
            self.update_default_output_dir()

    def select_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Selecciona donde guardar los archivos")
        if selected:
            self.output_dir.set(selected)

    def start_conversion(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        raw_input = self.input_dir.get().strip()
        if not raw_input:
            messagebox.showwarning("Falta carpeta", "Selecciona la carpeta de archivos.")
            return

        input_dir = Path(raw_input).resolve()
        if not input_dir.is_dir():
            messagebox.showerror("Ruta no valida", f"No existe la carpeta:\n{input_dir}")
            return

        output_format = get_output_format(self.output_format.get())
        raw_output = self.output_dir.get().strip()
        output_dir = (
            Path(raw_output).resolve()
            if raw_output
            else default_output_dir(input_dir, output_format)
        )

        self.clear_log()
        self.progress["value"] = 0
        self.progress_text.set("0 / 0")
        output_kind = get_conversion_kind(output_format.kind)
        self.status.set(f"Buscando {output_kind.plural_label}...")
        self.cancel_requested.clear()
        self.convert_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        self.worker = threading.Thread(
            target=self.run_conversion,
            args=(input_dir, output_dir, output_format, self.recursive.get()),
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
        input_dir: Path,
        output_dir: Path,
        output_format: ConversionFormat,
        recursive: bool,
    ) -> None:
        suffix = output_format.output_suffix
        files = iter_supported_files(input_dir, recursive, output_format)

        if not files:
            self.events.put(("empty", input_dir))
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

            relative_parent = source.parent.relative_to(input_dir)
            target_dir = output_dir / relative_parent
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = unique_output_path(target_dir, source.stem, suffix)

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
                self.status.set(f"Convirtiendo {output_kind.plural_label}...")
            elif event == "progress":
                current, total = payload  # type: ignore[misc]
                self.progress["value"] = current
                self.progress_text.set(f"{current} / {total}")
            elif event == "log":
                self.append_log(str(payload))
            elif event == "empty":
                self.convert_button.configure(state="normal")
                self.cancel_button.configure(state="disabled")
                self.status.set("No se encontraron archivos soportados.")
                messagebox.showinfo(
                    "Sin archivos",
                    f"No se encontraron archivos soportados en:\n{payload}",
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
