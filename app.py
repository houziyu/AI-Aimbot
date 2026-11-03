"""One runtime loop shared by the PyTorch, ONNX, and TensorRT entry points."""

import logging
import time

from runtime import PerformanceStats, Settings, prepare_frame, select_target


class WindowsControls:
    def __init__(self, quit_key):
        import win32api
        import win32con

        self.api = win32api
        self.move_flag = win32con.MOUSEEVENTF_MOVE
        self.quit_code = ord(quit_key.upper())

    def should_quit(self):
        return bool(self.api.GetAsyncKeyState(self.quit_code) & 0x8000)

    def enabled(self):
        return bool(self.api.GetKeyState(0x14) & 1)

    def move(self, dx, dy):
        if dx or dy:
            self.api.mouse_event(self.move_flag, dx, dy, 0, 0)


def draw_targets(cv2, bgr, targets):
    display = bgr.copy()
    color = (0, 220, 0)
    for x, y, width, height, confidence in targets:
        left, top = int(x - width / 2), int(y - height / 2)
        right, bottom = int(x + width / 2), int(y + height / 2)
        cv2.rectangle(display, (left, top), (right, bottom), color, 2)
        cv2.putText(display, f"Human: {confidence:.1%}", (left, max(15, top - 5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return display


def run_loop(settings, backend, capture, controls, cv2):
    """Own capture cleanup on failures, keyboard interrupts, and preview exits."""
    previous = None
    revision = capture.revision
    stats = PerformanceStats()
    count = 0
    report_start = time.perf_counter()
    try:
        while not controls.should_quit():
            started = time.perf_counter()
            frame = capture.read()
            if frame is None:
                previous = None
                continue
            captured = time.perf_counter()
            if revision != capture.revision:
                previous = None
                revision = capture.revision
            rgb, bgr = prepare_frame(frame, settings)
            image = backend.preprocess(rgb)
            if settings.performanceDisplay:
                backend.synchronize()
            preprocessed = time.perf_counter()
            prediction = backend.infer(image)
            if settings.performanceDisplay:
                backend.synchronize()
            inferred = time.perf_counter()
            targets = backend.postprocess(prediction)
            target = select_target(targets, settings.center, previous, settings.centerOfScreen)
            postprocessed = time.perf_counter()

            # The selected window may have moved or lost focus during inference.
            if capture.is_current() and not controls.should_quit():
                if target is None:
                    previous = None
                else:
                    x, y, _, height, _ = target
                    previous = (float(x), float(y))
                    offset = height * (0.38 if settings.headshot_mode else 0.2)
                    if controls.enabled():
                        controls.move(int((x - settings.center[0]) * settings.aaMovementAmp),
                                      int((y - offset - settings.center[1]) * settings.aaMovementAmp))
            else:
                previous = None

            preview_quit = False
            if settings.visuals:
                cv2.imshow("Live Feed", draw_targets(cv2, bgr, targets))
                preview_quit = (cv2.waitKey(1) & 0xFF) == ord(settings.aaQuitKey.lower())
            finished = time.perf_counter()
            if settings.performanceDisplay:
                stats.record({"capture": captured - started, "preprocess": preprocessed - captured,
                              "inference": inferred - preprocessed, "postprocess": postprocessed - inferred,
                              "total": finished - started})
            count += 1
            elapsed = finished - report_start
            if elapsed >= 1:
                if settings.cpsDisplay:
                    print(f"CPS: {count / elapsed:.1f}")
                if settings.performanceDisplay:
                    print(stats.summary())
                count = 0
                report_start = finished
            if preview_quit:
                break
    finally:
        for cleanup in (capture.close, cv2.destroyAllWindows):
            try:
                cleanup()
            except Exception:
                logging.exception("Could not fully clean up runtime resources")


def run(backend_name):
    import config
    from inference import create_backend

    settings = Settings.from_module(config)
    backend = create_backend(backend_name, settings)
    print(backend.description)
    backend.warmup()  # Validate execution before starting capture or accepting mouse input.
    import cv2
    from gameSelection import open_capture

    controls = WindowsControls(settings.aaQuitKey)
    capture = open_capture(settings)
    print(f"CAPS_LOCK toggles control; {settings.aaQuitKey.upper()} quits. Control pauses outside the selected window.")
    run_loop(settings, backend, capture, controls, cv2)


def cli(main):
    try:
        main()
    except KeyboardInterrupt:
        print("Stopped.")
    except Exception:
        logging.exception("Unable to run the application")
        raise SystemExit(1)
