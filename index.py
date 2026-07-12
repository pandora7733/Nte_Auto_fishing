import ctypes
import os
import cv2
import numpy as np
import mss
import time
import tkinter as tk
from tkinter import messagebox, simpledialog
import threading
from PIL import Image, ImageTk

# Windows DPI 인식
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.path.join(BASE_DIR, "templates")
MINT_TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, "mint.png")
YELLOW_TEMPLATE_PATH = os.path.join(TEMPLATE_DIR, "yellow.png")

# 전역 변수
is_running = False
is_previewing = False
fish_active = False
custom_monitor = None
preview_bgr = None
preview_lock = threading.Lock()
last_key_state = "없음"
last_mint_x = None
last_yellow_x = None
last_mint_score = 0.0
last_yellow_score = 0.0
last_mint_box = None  # (x, y, w, h)
last_yellow_box = None
PREVIEW_MAX_WIDTH = 520
FISH_GONE_FRAMES = 15
match_threshold = 0.70

mint_template = None  # BGR
yellow_template = None

algorithm_steps = []
current_step_index = None
algo_status_text = "대기"

user32 = ctypes.windll.user32
_prev_mouse_buttons = {"left": False, "right": False, "middle": False}
_last_click_text = "클릭 없음"
_last_click_expire = 0.0
_key_down_state = {"a": False, "d": False}

# --- SendInput 상수/구조체 ---
INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
KEYEVENTF_EXTENDEDKEY = 0x0001
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_ABSOLUTE = 0x8000
MOUSEEVENTF_VIRTUALDESK = 0x4000
SM_XVIRTUALSCREEN = 76
SM_YVIRTUALSCREEN = 77
SM_CXVIRTUALSCREEN = 78
SM_CYVIRTUALSCREEN = 79
MAPVK_VK_TO_VSC = 0

# 키 이름 -> 가상키
VK_MAP = {
    "a": 0x41,
    "d": 0x44,
    "f": 0x46,
    "esc": 0x1B,
    "escape": 0x1B,
}

WATCH_KEYS = [
    (0x41, "A"), (0x44, "D"), (0x57, "W"), (0x53, "S"),
    (0x20, "Space"), (0x10, "Shift"), (0x11, "Ctrl"), (0x12, "Alt"),
    (0x45, "E"), (0x51, "Q"), (0x46, "F"), (0x52, "R"),
    (0x1B, "Esc"),
]


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", ctypes.c_long),
        ("dy", ctypes.c_long),
        ("mouseData", ctypes.c_ulong),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.c_void_p),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", ctypes.c_ulong),
        ("wParamL", ctypes.c_short),
        ("wParamH", ctypes.c_ushort),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("union", INPUT_UNION),
    ]


def _send_input(*inputs):
    n = len(inputs)
    arr = (INPUT * n)(*inputs)
    sent = user32.SendInput(n, ctypes.byref(arr), ctypes.sizeof(INPUT))
    return sent == n


def _vk_to_scan(vk):
    return user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF


def _is_extended_vk(vk):
    # Esc는 extended 아님. 필요 시 확장.
    return vk in (0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x21, 0x22, 0x23, 0x24)


def _make_key_input(vk, key_up=False):
    scan = _vk_to_scan(vk)
    flags = KEYEVENTF_SCANCODE
    if key_up:
        flags |= KEYEVENTF_KEYUP
    if _is_extended_vk(vk):
        flags |= KEYEVENTF_EXTENDEDKEY
    inp = INPUT()
    inp.type = INPUT_KEYBOARD
    inp.union.ki = KEYBDINPUT(
        wVk=0,
        wScan=scan,
        dwFlags=flags,
        time=0,
        dwExtraInfo=None,
    )
    return inp


def press_key(name):
    key = name.lower()
    vk = VK_MAP.get(key)
    if vk is None:
        return
    _send_input(_make_key_input(vk, key_up=False))
    if key in _key_down_state:
        _key_down_state[key] = True


def release_key(name):
    key = name.lower()
    vk = VK_MAP.get(key)
    if vk is None:
        return
    _send_input(_make_key_input(vk, key_up=True))
    if key in _key_down_state:
        _key_down_state[key] = False


def tap_key(name):
    press_key(name)
    time.sleep(0.04)
    release_key(name)


def release_ad():
    release_key("a")
    release_key("d")


def _to_absolute_mouse(x, y):
    """가상 데스크톱 기준 0~65535 절대좌표."""
    vx = user32.GetSystemMetrics(SM_XVIRTUALSCREEN)
    vy = user32.GetSystemMetrics(SM_YVIRTUALSCREEN)
    vw = max(user32.GetSystemMetrics(SM_CXVIRTUALSCREEN), 1)
    vh = max(user32.GetSystemMetrics(SM_CYVIRTUALSCREEN), 1)
    ax = int((x - vx) * 65535 / vw)
    ay = int((y - vy) * 65535 / vh)
    return max(0, min(65535, ax)), max(0, min(65535, ay))


def _make_mouse_input(dx, dy, flags):
    inp = INPUT()
    inp.type = INPUT_MOUSE
    inp.union.mi = MOUSEINPUT(
        dx=dx,
        dy=dy,
        mouseData=0,
        dwFlags=flags,
        time=0,
        dwExtraInfo=None,
    )
    return inp


def click_at(x, y):
    """화면 절대 좌표에 SendInput 좌클릭."""
    ax, ay = _to_absolute_mouse(int(x), int(y))
    flags_move = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE | MOUSEEVENTF_VIRTUALDESK
    _send_input(_make_mouse_input(ax, ay, flags_move))
    time.sleep(0.03)
    _send_input(_make_mouse_input(0, 0, MOUSEEVENTF_LEFTDOWN))
    time.sleep(0.04)
    _send_input(_make_mouse_input(0, 0, MOUSEEVENTF_LEFTUP))


def get_mouse_state():
    pt = POINT()
    user32.GetCursorPos(ctypes.byref(pt))
    left = bool(user32.GetAsyncKeyState(0x01) & 0x8000)
    right = bool(user32.GetAsyncKeyState(0x02) & 0x8000)
    middle = bool(user32.GetAsyncKeyState(0x04) & 0x8000)
    return pt.x, pt.y, left, right, middle


def get_pressed_keys():
    pressed = []
    for vk, name in WATCH_KEYS:
        if user32.GetAsyncKeyState(vk) & 0x8000:
            pressed.append(name)
    return pressed


def update_click_flash(left, right, middle):
    global _last_click_text, _last_click_expire, _prev_mouse_buttons
    now = time.time()
    events = []
    if left and not _prev_mouse_buttons["left"]:
        events.append("좌클릭")
    if right and not _prev_mouse_buttons["right"]:
        events.append("우클릭")
    if middle and not _prev_mouse_buttons["middle"]:
        events.append("휠클릭")
    _prev_mouse_buttons = {"left": left, "right": right, "middle": middle}
    if events:
        _last_click_text = " + ".join(events)
        _last_click_expire = now + 0.8
    if now > _last_click_expire:
        _last_click_text = "클릭 없음"
    return _last_click_text


def format_button_state(pressed):
    return "● 눌림" if pressed else "○ 해제"


def interruptible_sleep(seconds):
    end = time.time() + max(0.0, float(seconds))
    while is_running and time.time() < end:
        time.sleep(0.05)
    return is_running


def ensure_template_dir():
    os.makedirs(TEMPLATE_DIR, exist_ok=True)


def load_templates():
    """디스크에서 템플릿 로드."""
    global mint_template, yellow_template
    mint_template = None
    yellow_template = None
    if os.path.isfile(MINT_TEMPLATE_PATH):
        img = cv2.imread(MINT_TEMPLATE_PATH, cv2.IMREAD_COLOR)
        if img is not None and img.size > 0:
            mint_template = img
    if os.path.isfile(YELLOW_TEMPLATE_PATH):
        img = cv2.imread(YELLOW_TEMPLATE_PATH, cv2.IMREAD_COLOR)
        if img is not None and img.size > 0:
            yellow_template = img


def save_template(name, bgr_img):
    ensure_template_dir()
    path = MINT_TEMPLATE_PATH if name == "mint" else YELLOW_TEMPLATE_PATH
    cv2.imwrite(path, bgr_img)
    load_templates()


def templates_ready():
    return mint_template is not None and yellow_template is not None


def match_template(frame_bgr, template, thresh):
    """
    템플릿 매칭. 성공 시 (center_x, score, box) / 실패 시 (None, score, None)
    box = (x, y, w, h)
    """
    if template is None or frame_bgr is None:
        return None, 0.0, None
    th, tw = template.shape[:2]
    fh, fw = frame_bgr.shape[:2]
    if th > fh or tw > fw:
        return None, 0.0, None

    res = cv2.matchTemplate(frame_bgr, template, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    score = float(max_val)
    if score < thresh:
        return None, score, None
    x, y = max_loc
    cx = x + tw // 2
    return cx, score, (x, y, tw, th)


def apply_key_control(mint_x, yellow_x):
    """민트/노란 좌표 차이에 따라 A/D (SendInput)."""
    if mint_x is None or yellow_x is None:
        release_ad()
        return "대기 (미감지)"

    if yellow_x < mint_x - 5:
        release_key("a")
        press_key("d")
        return "D (오른쪽)"
    if yellow_x > mint_x + 5:
        release_key("d")
        press_key("a")
        return "A (왼쪽)"

    release_ad()
    return "중립 (맞춤)"


def get_tk_to_mss_scale():
    with mss.MSS() as sct:
        mon = sct.monitors[1]
    tk_w = max(root.winfo_screenwidth(), 1)
    tk_h = max(root.winfo_screenheight(), 1)
    return mon["width"] / tk_w, mon["height"] / tk_h


def tk_point_to_mss(x, y):
    scale_x, scale_y = get_tk_to_mss_scale()
    return int(round(x * scale_x)), int(round(y * scale_y))


def tk_region_to_mss(left, top, right, bottom):
    scale_x, scale_y = get_tk_to_mss_scale()
    left_m = int(round(min(left, right) * scale_x))
    top_m = int(round(min(top, bottom) * scale_y))
    right_m = int(round(max(left, right) * scale_x))
    bottom_m = int(round(max(top, bottom) * scale_y))
    return {
        "left": left_m,
        "top": top_m,
        "width": max(1, right_m - left_m),
        "height": max(1, bottom_m - top_m),
    }


def build_preview_frame(
    img_bgr, mint_x, yellow_x, mint_score, yellow_score,
    mint_box, yellow_box, key_state, thresh,
):
    """캡처 + 템플릿 매칭 박스/점수 미리보기."""
    view = img_bgr.copy()
    h, w = view.shape[:2]

    if mint_box is not None:
        x, y, bw, bh = mint_box
        cv2.rectangle(view, (x, y), (x + bw, y + bh), (255, 255, 0), 2)
    if yellow_box is not None:
        x, y, bw, bh = yellow_box
        cv2.rectangle(view, (x, y), (x + bw, y + bh), (0, 255, 255), 2)

    if mint_x is not None:
        cv2.line(view, (mint_x, 0), (mint_x, h), (255, 255, 0), 2)
    if yellow_x is not None:
        cv2.line(view, (yellow_x, 0), (yellow_x, h), (0, 255, 255), 2)

    display_h = max(h * 2, 48)
    view = cv2.resize(view, (w, display_h), interpolation=cv2.INTER_NEAREST)

    bar = np.zeros((44, view.shape[1], 3), dtype=np.uint8)
    bar[:] = (30, 30, 30)
    line1 = f"Mint:{mint_x} ({mint_score:.2f})  Yellow:{yellow_x} ({yellow_score:.2f})  thr:{thresh:.2f}"
    line2 = f"Key:{key_state}  size:{w}x{h}"
    cv2.putText(bar, line1, (6, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 255, 180), 1, cv2.LINE_AA)
    cv2.putText(bar, line2, (6, 36), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (200, 200, 200), 1, cv2.LINE_AA)
    return np.vstack((bar, view))


def capture_loop():
    """캡처·템플릿 매칭 미리보기. fish_active일 때만 A/D."""
    global is_previewing, preview_bgr
    global last_key_state, last_mint_x, last_yellow_x
    global last_mint_score, last_yellow_score, last_mint_box, last_yellow_box

    with mss.MSS() as sct:
        while is_previewing and custom_monitor is not None:
            try:
                screen = np.array(sct.grab(custom_monitor))
            except Exception:
                time.sleep(0.05)
                continue

            img_bgr = cv2.cvtColor(screen, cv2.COLOR_BGRA2BGR)
            thresh = match_threshold

            mint_x, mint_score, mint_box = match_template(img_bgr, mint_template, thresh)
            yellow_x, yellow_score, yellow_box = match_template(img_bgr, yellow_template, thresh)

            if fish_active:
                key_state = apply_key_control(mint_x, yellow_x)
            else:
                release_ad()
                key_state = "정지"

            frame = build_preview_frame(
                img_bgr, mint_x, yellow_x, mint_score, yellow_score,
                mint_box, yellow_box, key_state, thresh,
            )

            with preview_lock:
                preview_bgr = frame
                last_key_state = key_state
                last_mint_x = mint_x
                last_yellow_x = yellow_x
                last_mint_score = mint_score
                last_yellow_score = yellow_score
                last_mint_box = mint_box
                last_yellow_box = yellow_box

            time.sleep(0.02)

    release_ad()


def run_fish_step():
    global fish_active
    if custom_monitor is None:
        return False
    if not templates_ready():
        set_algo_status("오류: 민트/노랑 템플릿 필요")
        return False

    if not is_previewing:
        start_preview()

    fish_active = True
    gone = 0
    seen_once = False

    while is_running:
        with preview_lock:
            mint_x = last_mint_x
            yellow_x = last_yellow_x

        if mint_x is not None or yellow_x is not None:
            seen_once = True
            gone = 0
        else:
            gone += 1
            if seen_once and gone >= FISH_GONE_FRAMES:
                break
        time.sleep(0.02)

    fish_active = False
    release_ad()
    return is_running


def step_label(step):
    idx = step["index"]
    t = step["type"]
    if t == "sleep":
        return f"[{idx}] sleep {step['seconds']}s"
    if t == "key":
        return f"[{idx}] key {step['key'].upper()}"
    if t == "mouse_click":
        return f"[{idx}] mouse_click ({step['x']},{step['y']})"
    if t == "fish":
        return f"[{idx}] fish (바 소실까지)"
    return f"[{idx}] {t}"


def reindex_steps():
    for i, step in enumerate(algorithm_steps):
        step["index"] = i


def refresh_algo_list(select_index=None):
    algo_listbox.delete(0, tk.END)
    for step in algorithm_steps:
        algo_listbox.insert(tk.END, step_label(step))
    if select_index is not None and 0 <= select_index < len(algorithm_steps):
        algo_listbox.selection_clear(0, tk.END)
        algo_listbox.selection_set(select_index)
        algo_listbox.activate(select_index)


def set_algo_status(text):
    global algo_status_text
    algo_status_text = text


def execute_step(step):
    t = step["type"]
    if t == "sleep":
        set_algo_status(f"실행 중: [{step['index']}] sleep {step['seconds']}s")
        return interruptible_sleep(step["seconds"])

    if t == "key":
        set_algo_status(f"실행 중: [{step['index']}] key {step['key'].upper()}")
        tap_key(step["key"])
        return interruptible_sleep(0.15)

    if t == "mouse_click":
        set_algo_status(f"실행 중: [{step['index']}] mouse_click ({step['x']},{step['y']})")
        click_at(step["x"], step["y"])
        return interruptible_sleep(0.15)

    if t == "fish":
        set_algo_status(f"실행 중: [{step['index']}] fish (바 소실까지)")
        return run_fish_step()

    return is_running


def algorithm_loop():
    global is_running, current_step_index, fish_active

    while is_running:
        if not algorithm_steps:
            break
        steps = sorted(algorithm_steps, key=lambda s: s["index"])
        for step in steps:
            if not is_running:
                break
            current_step_index = step["index"]
            if not execute_step(step):
                break
        current_step_index = None

    fish_active = False
    release_ad()
    set_algo_status("정지됨")
    is_running = False


def update_gui_preview():
    if not root.winfo_exists():
        return

    frame = None
    with preview_lock:
        if preview_bgr is not None:
            frame = preview_bgr.copy()
        mint_x = last_mint_x
        yellow_x = last_yellow_x
        mint_score = last_mint_score
        yellow_score = last_yellow_score
        key_state = last_key_state

    if frame is not None:
        h, w = frame.shape[:2]
        scale = min(1.0, PREVIEW_MAX_WIDTH / max(w, 1))
        if scale < 1.0:
            frame = cv2.resize(
                frame, (int(w * scale), int(h * scale)), interpolation=cv2.INTER_AREA
            )
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        photo = ImageTk.PhotoImage(image=Image.fromarray(rgb))
        preview_label.configure(image=photo, text="")
        preview_label.image = photo

    if custom_monitor:
        region_info_label.config(
            text=(
                f"캡처 영역  left={custom_monitor['left']}  top={custom_monitor['top']}  "
                f"{custom_monitor['width']}x{custom_monitor['height']}"
            )
        )
        detect_info_label.config(
            text=(
                f"민트 X:{mint_x if mint_x is not None else '-'} ({mint_score:.2f})  "
                f"노랑 X:{yellow_x if yellow_x is not None else '-'} ({yellow_score:.2f})  "
                f"봇키:{key_state}"
            )
        )

    mint_status = "OK" if mint_template is not None else "없음"
    yellow_status = "OK" if yellow_template is not None else "없음"
    template_status_label.config(
        text=f"템플릿  민트:{mint_status}  노랑:{yellow_status}  임계값:{match_threshold:.2f}"
    )

    mx, my, lmb, rmb, mmb = get_mouse_state()
    click_flash = update_click_flash(lmb, rmb, mmb)
    pressed_keys = get_pressed_keys()

    mouse_pos_label.config(text=f"마우스 좌표: ({mx}, {my})")
    mouse_lmb_label.config(
        text=f"좌클릭  {format_button_state(lmb)}",
        fg="#00aa44" if lmb else "#666666",
    )
    mouse_rmb_label.config(
        text=f"우클릭  {format_button_state(rmb)}",
        fg="#00aa44" if rmb else "#666666",
    )
    mouse_mmb_label.config(
        text=f"휠클릭  {format_button_state(mmb)}",
        fg="#00aa44" if mmb else "#666666",
    )
    mouse_click_event_label.config(
        text=f"최근 클릭: {click_flash}",
        fg="#cc6600" if click_flash != "클릭 없음" else "#666666",
    )

    if pressed_keys:
        keyboard_state_label.config(
            text="키보드: " + " + ".join(pressed_keys), fg="#0066cc"
        )
    else:
        keyboard_state_label.config(text="키보드: (눌린 키 없음)", fg="#666666")

    a_down = "A" in pressed_keys
    d_down = "D" in pressed_keys
    ad_label.config(
        text=f"A [{'ON' if a_down else 'off'}]   D [{'ON' if d_down else 'off'}]",
        fg="#00aa44" if (a_down or d_down) else "#666666",
    )

    algo_status_label.config(text=algo_status_text)
    if current_step_index is not None and algorithm_steps:
        try:
            if algo_listbox.curselection() != (current_step_index,):
                algo_listbox.selection_clear(0, tk.END)
                if current_step_index < algo_listbox.size():
                    algo_listbox.selection_set(current_step_index)
                    algo_listbox.see(current_step_index)
        except tk.TclError:
            pass

    root.after(33, update_gui_preview)


def start_preview():
    global is_previewing
    if is_previewing or custom_monitor is None:
        return
    is_previewing = True
    threading.Thread(target=capture_loop, daemon=True).start()


def stop_preview():
    global is_previewing, fish_active
    is_previewing = False
    fish_active = False
    time.sleep(0.05)


def _select_region_modal(title_text):
    result = {"region": None}
    root.withdraw()
    root.update_idletasks()
    time.sleep(0.2)

    overlay = tk.Toplevel(root)
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-alpha", 0.25)
    overlay.attributes("-topmost", True)
    overlay.config(cursor="cross")
    overlay.focus_force()
    overlay.grab_set()

    canvas = tk.Canvas(overlay, bg="gray", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        overlay.winfo_screenwidth() // 2,
        40,
        text=title_text + " (Esc: 취소)",
        fill="white",
        font=("맑은 고딕", 14),
    )

    rect_id = None
    start_root_x = start_root_y = 0

    def on_press(event):
        nonlocal start_root_x, start_root_y, rect_id
        start_root_x, start_root_y = event.x_root, event.y_root
        rect_id = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="red", width=3
        )

    def on_drag(event):
        if rect_id is None:
            return
        x0 = start_root_x - overlay.winfo_rootx()
        y0 = start_root_y - overlay.winfo_rooty()
        canvas.coords(rect_id, x0, y0, event.x, event.y)

    def finish(end_root_x, end_root_y, cancelled=False):
        try:
            overlay.grab_release()
        except tk.TclError:
            pass
        overlay.destroy()
        root.deiconify()
        root.lift()
        if not cancelled:
            region = tk_region_to_mss(
                start_root_x, start_root_y, end_root_x, end_root_y
            )
            if region["width"] > 3 and region["height"] > 3:
                result["region"] = region

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", lambda e: finish(e.x_root, e.y_root))
    overlay.bind("<Escape>", lambda _e: finish(0, 0, cancelled=True))
    root.wait_window(overlay)
    return result["region"]


def _select_crosshair_point(title_text):
    """원+십자가 가이드로 클릭 좌표 1점 선택."""
    result = {"point": None}
    root.withdraw()
    root.update_idletasks()
    time.sleep(0.2)

    overlay = tk.Toplevel(root)
    overlay.attributes("-fullscreen", True)
    overlay.attributes("-alpha", 0.30)
    overlay.attributes("-topmost", True)
    overlay.config(cursor="none")
    overlay.focus_force()
    overlay.grab_set()

    canvas = tk.Canvas(overlay, bg="#404040", highlightthickness=0)
    canvas.pack(fill="both", expand=True)
    canvas.create_text(
        overlay.winfo_screenwidth() // 2,
        40,
        text=title_text + " — 십자가 중심에 맞춘 뒤 클릭 (Esc: 취소)",
        fill="white",
        font=("맑은 고딕", 14),
    )

    r = 28
    circle = canvas.create_oval(0, 0, 0, 0, outline="#00ff88", width=2)
    hline = canvas.create_line(0, 0, 0, 0, fill="#00ff88", width=2)
    vline = canvas.create_line(0, 0, 0, 0, fill="#00ff88", width=2)
    center_dot = canvas.create_oval(0, 0, 0, 0, fill="#ff4444", outline="")

    def draw_cross(x, y):
        canvas.coords(circle, x - r, y - r, x + r, y + r)
        canvas.coords(hline, x - r - 8, y, x + r + 8, y)
        canvas.coords(vline, x, y - r - 8, x, y + r + 8)
        canvas.coords(center_dot, x - 2, y - 2, x + 2, y + 2)

    def on_move(event):
        draw_cross(event.x, event.y)

    def finish(x_root, y_root, cancelled=False):
        try:
            overlay.grab_release()
        except tk.TclError:
            pass
        overlay.destroy()
        root.deiconify()
        root.lift()
        if not cancelled:
            mx, my = tk_point_to_mss(x_root, y_root)
            result["point"] = (mx, my)

    def on_click(event):
        finish(event.x_root, event.y_root)

    canvas.bind("<Motion>", on_move)
    canvas.bind("<ButtonPress-1>", on_click)
    overlay.bind("<Escape>", lambda _e: finish(0, 0, cancelled=True))
    root.wait_window(overlay)
    return result["point"]


def select_capture_area():
    global custom_monitor
    if is_running:
        stop_macro()
    stop_preview()
    region = _select_region_modal("드래그로 낚시 캡처 영역을 지정하세요")
    if region is None:
        return
    custom_monitor = region
    if custom_monitor["width"] > 10 and custom_monitor["height"] > 10:
        status_label.config(
            text=f"상태: 미리보기 중 ({custom_monitor['width']}x{custom_monitor['height']})",
            fg="blue",
        )
        start_preview()
    else:
        custom_monitor = None
        messagebox.showwarning("경고", "지정한 영역이 너무 작습니다.")


def capture_template(kind):
    """kind: 'mint' | 'yellow' — 화면에서 템플릿 조각 캡처."""
    if is_running:
        messagebox.showinfo("안내", "실행 중에는 템플릿을 캡처할 수 없습니다.")
        return

    label = "민트" if kind == "mint" else "노랑"
    was_previewing = is_previewing
    stop_preview()

    region = _select_region_modal(f"{label} 바 조각을 작게 드래그해 템플릿으로 저장하세요")
    if region is None:
        if was_previewing and custom_monitor is not None:
            start_preview()
        return

    with mss.MSS() as sct:
        shot = np.array(sct.grab(region))
    img_bgr = cv2.cvtColor(shot, cv2.COLOR_BGRA2BGR)
    if img_bgr.shape[0] < 3 or img_bgr.shape[1] < 3:
        messagebox.showwarning("경고", "템플릿이 너무 작습니다.")
        if was_previewing and custom_monitor is not None:
            start_preview()
        return

    save_template(kind, img_bgr)
    messagebox.showinfo(
        "저장됨",
        f"{label} 템플릿 저장: {os.path.basename(MINT_TEMPLATE_PATH if kind == 'mint' else YELLOW_TEMPLATE_PATH)}\n"
        f"크기: {img_bgr.shape[1]}x{img_bgr.shape[0]}",
    )
    if custom_monitor is not None:
        start_preview()


def on_threshold_change(val):
    global match_threshold
    match_threshold = float(val)


def add_step_dialog():
    if is_running:
        messagebox.showinfo("안내", "실행 중에는 단계를 수정할 수 없습니다.")
        return

    dlg = tk.Toplevel(root)
    dlg.title("단계 추가")
    dlg.attributes("-topmost", True)
    dlg.geometry("280x280")
    dlg.transient(root)
    dlg.grab_set()

    tk.Label(dlg, text="추가할 단계 타입", font=("맑은 고딕", 10)).pack(pady=10)

    def close():
        try:
            dlg.grab_release()
        except tk.TclError:
            pass
        dlg.destroy()

    def add_sleep():
        close()
        sec = simpledialog.askfloat(
            "Sleep", "대기 시간(초):", minvalue=0.1, maxvalue=3600.0, parent=root
        )
        if sec is None:
            return
        algorithm_steps.append(
            {"index": len(algorithm_steps), "type": "sleep", "seconds": float(sec)}
        )
        reindex_steps()
        refresh_algo_list(len(algorithm_steps) - 1)

    def add_key(key_name):
        close()
        algorithm_steps.append(
            {"index": len(algorithm_steps), "type": "key", "key": key_name}
        )
        reindex_steps()
        refresh_algo_list(len(algorithm_steps) - 1)

    def add_mouse():
        close()
        point = _select_crosshair_point("마우스 클릭 위치를 십자가 중심에 맞추세요")
        if point is None:
            messagebox.showinfo("안내", "클릭 위치 지정이 취소되었습니다.")
            return
        x, y = point
        algorithm_steps.append(
            {"index": len(algorithm_steps), "type": "mouse_click", "x": x, "y": y}
        )
        reindex_steps()
        refresh_algo_list(len(algorithm_steps) - 1)

    def add_fish():
        close()
        if custom_monitor is None:
            messagebox.showerror("오류", "먼저 낚시 캡처 영역을 지정해주세요.")
            return
        if not templates_ready():
            messagebox.showerror(
                "오류",
                "민트/노랑 템플릿이 필요합니다.\n[민트 템플릿] / [노랑 템플릿] 버튼으로 캡처하세요.",
            )
            return
        algorithm_steps.append({"index": len(algorithm_steps), "type": "fish"})
        reindex_steps()
        refresh_algo_list(len(algorithm_steps) - 1)

    tk.Button(dlg, text="Sleep (타이머)", width=22, command=add_sleep).pack(pady=3)
    tk.Button(dlg, text="Esc 키", width=22, command=lambda: add_key("esc")).pack(pady=3)
    tk.Button(dlg, text="F 키", width=22, command=lambda: add_key("f")).pack(pady=3)
    tk.Button(dlg, text="마우스 클릭 (십자가)", width=22, command=add_mouse).pack(pady=3)
    tk.Button(dlg, text="낚시 (바 소실까지)", width=22, command=add_fish).pack(pady=3)
    tk.Button(dlg, text="취소", width=22, command=close).pack(pady=8)


def delete_selected_step():
    if is_running:
        messagebox.showinfo("안내", "실행 중에는 단계를 수정할 수 없습니다.")
        return
    sel = algo_listbox.curselection()
    if not sel:
        return
    idx = sel[0]
    del algorithm_steps[idx]
    reindex_steps()
    refresh_algo_list(min(idx, len(algorithm_steps) - 1) if algorithm_steps else None)


def move_step(delta):
    if is_running:
        messagebox.showinfo("안내", "실행 중에는 단계를 수정할 수 없습니다.")
        return
    sel = algo_listbox.curselection()
    if not sel:
        return
    idx = sel[0]
    new_idx = idx + delta
    if new_idx < 0 or new_idx >= len(algorithm_steps):
        return
    algorithm_steps[idx], algorithm_steps[new_idx] = (
        algorithm_steps[new_idx],
        algorithm_steps[idx],
    )
    reindex_steps()
    refresh_algo_list(new_idx)


def start_macro():
    global is_running
    if is_running:
        return
    if not algorithm_steps:
        messagebox.showerror("오류", "알고리즘 단계가 없습니다.")
        return

    has_fish = any(s["type"] == "fish" for s in algorithm_steps)
    if has_fish:
        if custom_monitor is None:
            messagebox.showerror("오류", "fish 단계: 캡처 영역이 필요합니다.")
            return
        if not templates_ready():
            messagebox.showerror("오류", "fish 단계: 민트/노랑 템플릿이 필요합니다.")
            return
        if not is_previewing:
            start_preview()

    is_running = True
    set_algo_status("시퀀스 시작")
    status_label.config(
        text="상태: 실행 중 (입력이 안 되면 관리자 권한으로 실행)",
        fg="green",
    )
    threading.Thread(target=algorithm_loop, daemon=True).start()


def stop_macro():
    global is_running, fish_active, current_step_index
    is_running = False
    fish_active = False
    current_step_index = None
    release_ad()
    set_algo_status("정지됨")
    if custom_monitor:
        status_label.config(text="상태: 정지됨 (미리보기 유지)", fg="red")
    else:
        status_label.config(text="상태: 정지됨", fg="red")


def on_closing():
    stop_macro()
    stop_preview()
    root.destroy()


# GUI
root = tk.Tk()
root.title("자동 낚시 봇")
root.geometry("620x920")
root.attributes("-topmost", True)
root.minsize(540, 760)

ensure_template_dir()
load_templates()

status_label = tk.Label(
    root,
    text="상태: 캡처 영역·템플릿 설정 필요 (게임 입력은 관리자 실행 권장)",
    font=("맑은 고딕", 10),
)
status_label.pack(pady=(10, 4))

region_info_label = tk.Label(
    root, text="캡처 영역: 미지정", font=("맑은 고딕", 9), fg="#444444"
)
region_info_label.pack()

detect_info_label = tk.Label(
    root, text="감지: -", font=("맑은 고딕", 9), fg="#444444"
)
detect_info_label.pack(pady=(0, 2))

template_status_label = tk.Label(
    root, text="템플릿  민트:없음  노랑:없음", font=("맑은 고딕", 9), fg="#444444"
)
template_status_label.pack(pady=(0, 4))

# 템플릿 / 임계값
tpl_frame = tk.LabelFrame(
    root, text="템플릿 매칭", font=("맑은 고딕", 9), padx=8, pady=6
)
tpl_frame.pack(fill="x", padx=10, pady=(0, 6))

tpl_btn_row = tk.Frame(tpl_frame)
tpl_btn_row.pack(fill="x")
tk.Button(
    tpl_btn_row, text="민트 템플릿 캡처", width=16,
    command=lambda: capture_template("mint"),
).pack(side="left", padx=2)
tk.Button(
    tpl_btn_row, text="노랑 템플릿 캡처", width=16,
    command=lambda: capture_template("yellow"),
).pack(side="left", padx=2)

thr_row = tk.Frame(tpl_frame)
thr_row.pack(fill="x", pady=(6, 0))
tk.Label(thr_row, text="매칭 임계값", font=("맑은 고딕", 9)).pack(side="left")
threshold_scale = tk.Scale(
    thr_row,
    from_=0.40,
    to=0.95,
    resolution=0.01,
    orient="horizontal",
    length=280,
    command=on_threshold_change,
)
threshold_scale.set(match_threshold)
threshold_scale.pack(side="left", padx=6)

# 입력 모니터
input_frame = tk.LabelFrame(
    root, text="입력 실시간 모니터 (SendInput)", font=("맑은 고딕", 9), padx=8, pady=6
)
input_frame.pack(fill="x", padx=10, pady=(0, 6))

mouse_pos_label = tk.Label(
    input_frame, text="마우스 좌표: (-, -)", font=("맑은 고딕", 9), anchor="w"
)
mouse_pos_label.pack(fill="x")

mouse_btn_row = tk.Frame(input_frame)
mouse_btn_row.pack(fill="x", pady=(2, 0))
mouse_lmb_label = tk.Label(
    mouse_btn_row, text="좌클릭  ○ 해제", font=("맑은 고딕", 9), fg="#666666", width=14, anchor="w"
)
mouse_lmb_label.pack(side="left")
mouse_rmb_label = tk.Label(
    mouse_btn_row, text="우클릭  ○ 해제", font=("맑은 고딕", 9), fg="#666666", width=14, anchor="w"
)
mouse_rmb_label.pack(side="left")
mouse_mmb_label = tk.Label(
    mouse_btn_row, text="휠클릭  ○ 해제", font=("맑은 고딕", 9), fg="#666666", width=14, anchor="w"
)
mouse_mmb_label.pack(side="left")

mouse_click_event_label = tk.Label(
    input_frame, text="최근 클릭: 클릭 없음", font=("맑은 고딕", 9), fg="#666666", anchor="w"
)
mouse_click_event_label.pack(fill="x", pady=(2, 0))
keyboard_state_label = tk.Label(
    input_frame, text="키보드: (눌린 키 없음)", font=("맑은 고딕", 9), fg="#666666", anchor="w"
)
keyboard_state_label.pack(fill="x", pady=(4, 0))
ad_label = tk.Label(
    input_frame, text="A [off]   D [off]", font=("맑은 고딕", 10, "bold"), fg="#666666", anchor="w"
)
ad_label.pack(fill="x", pady=(2, 0))

preview_frame = tk.Frame(root, bg="#1e1e1e", padx=4, pady=4)
preview_frame.pack(fill="both", expand=True, padx=10, pady=4)
preview_label = tk.Label(
    preview_frame,
    text="캡처 영역 지정 후\n템플릿 매칭 결과가 여기에 표시됩니다",
    bg="#1e1e1e",
    fg="#aaaaaa",
    font=("맑은 고딕", 10),
    justify="center",
)
preview_label.pack(fill="both", expand=True)

algo_frame = tk.LabelFrame(
    root, text="알고리즘 (인덱스 순서 실행, 반복)", font=("맑은 고딕", 9), padx=8, pady=6
)
algo_frame.pack(fill="x", padx=10, pady=(0, 6))
algo_status_label = tk.Label(
    algo_frame, text="대기", font=("맑은 고딕", 9), fg="#0066aa", anchor="w"
)
algo_status_label.pack(fill="x")
algo_listbox = tk.Listbox(algo_frame, height=5, font=("Consolas", 10), exportselection=False)
algo_listbox.pack(fill="x", pady=4)
algo_btn_row = tk.Frame(algo_frame)
algo_btn_row.pack(fill="x")
tk.Button(algo_btn_row, text="단계 추가", width=10, command=add_step_dialog).pack(side="left", padx=2)
tk.Button(algo_btn_row, text="삭제", width=8, command=delete_selected_step).pack(side="left", padx=2)
tk.Button(algo_btn_row, text="▲ 위로", width=8, command=lambda: move_step(-1)).pack(side="left", padx=2)
tk.Button(algo_btn_row, text="▼ 아래로", width=8, command=lambda: move_step(1)).pack(side="left", padx=2)

btn_row = tk.Frame(root)
btn_row.pack(pady=8)
tk.Button(btn_row, text="캡처 영역 지정", command=select_capture_area, width=16, bg="#e0e0e0").grid(
    row=0, column=0, padx=4
)
tk.Button(btn_row, text="시작 (Start)", command=start_macro, width=14).grid(row=0, column=1, padx=4)
tk.Button(btn_row, text="정지 (Stop)", command=stop_macro, width=14).grid(row=0, column=2, padx=4)

hint_label = tk.Label(
    root,
    text="템플릿 매칭 + SendInput  |  마우스=십자가 중심 클릭  |  입력 실패 시 관리자 실행",
    font=("맑은 고딕", 8),
    fg="#666666",
)
hint_label.pack(pady=(0, 8))

root.protocol("WM_DELETE_WINDOW", on_closing)
root.after(33, update_gui_preview)

if __name__ == "__main__":
    root.mainloop()
