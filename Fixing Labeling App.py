# main.py
import os
import tkinter as tk
from tkinter import filedialog, messagebox
from typing import List, Tuple, Dict, Optional
from PIL import Image, ImageTk

# -------------------------
# RectManager (logic)
# -------------------------
class RectManager:
    """Store per-image normalized rectangles in YOLO style (cx,cy,w,h in 0..1).
    Supports adding with optional UID (to keep stable IDs across undo/redo).
    """
    def __init__(self):
        self.rectangles: Dict[str, List[Dict]] = {}
        self._next_uid: int = 1

    def _new_uid(self) -> int:
        uid = self._next_uid
        self._next_uid += 1
        return uid

    def load_from_txt(self, txt_path: str):
        rects = []
        if os.path.exists(txt_path):
            with open(txt_path, "r") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        tag = parts[0]
                        cx, cy, w, h = map(float, parts[1:])
                        rects.append({'uid': self._new_uid(), 'tag': tag, 'cx': cx, 'cy': cy, 'w': w, 'h': h})
        self.rectangles[txt_path] = rects

    def save_to_txt(self, txt_path: str):
        rects = self.rectangles.get(txt_path, [])
        with open(txt_path, "w") as f:
            for i, r in enumerate(rects):
                line = f"{r['tag']} {r['cx']} {r['cy']} {r['w']} {r['h']}"
                if i < len(rects) - 1:
                    line += "\n"
                f.write(line)

    def add_rect(self, txt_path: str, tag: str, cx: float, cy: float, w: float, h: float, uid: Optional[int] = None) -> int:
        rects = self.rectangles.setdefault(txt_path, [])
        if uid is None:
            uid = self._new_uid()
        else:
            # keep next uid monotonic
            if uid >= self._next_uid:
                self._next_uid = uid + 1
        rects.append({'uid': uid, 'tag': tag, 'cx': cx, 'cy': cy, 'w': w, 'h': h})
        return uid

    def delete_rect(self, txt_path: str, uid: int):
        rects = self.rectangles.get(txt_path, [])
        self.rectangles[txt_path] = [r for r in rects if r['uid'] != uid]

    def update_rect(self, txt_path: str, uid: int, cx: float, cy: float, w: float, h: float):
        rects = self.rectangles.get(txt_path, [])
        for r in rects:
            if r['uid'] == uid:
                r['cx'], r['cy'], r['w'], r['h'] = cx, cy, w, h
                return

    def update_tag(self, txt_path: str, uid: int, new_tag: str):
        rects = self.rectangles.get(txt_path, [])
        for r in rects:
            if r['uid'] == uid:
                r['tag'] = new_tag
                return

    def get_rect_by_uid(self, txt_path: str, uid: int) -> Optional[Dict]:
        for r in self.rectangles.get(txt_path, []):
            if r['uid'] == uid:
                return r
        return None

    @staticmethod
    def xyxy_to_cxcywh(x1, y1, x2, y2, img_w, img_h):
        cx = ((x1 + x2) / 2) / img_w
        cy = ((y1 + y2) / 2) / img_h
        w = abs(x2 - x1) / img_w
        h = abs(y2 - y1) / img_h
        return cx, cy, w, h

    @staticmethod
    def cxcywh_to_xyxy(cx, cy, w, h, img_w, img_h):
        cx *= img_w
        cy *= img_h
        w *= img_w
        h *= img_h
        x1 = cx - w / 2
        y1 = cy - h / 2
        x2 = cx + w / 2
        y2 = cy + h / 2
        return x1, y1, x2, y2

# -------------------------
# Action Stack (undo/redo)
# -------------------------
class ActionStack:
    """Simple undo/redo stack with a fixed capacity."""
    def __init__(self, capacity: int = 30):
        self.capacity = capacity
        self.stack: List[Dict] = []
        self.index = -1  # points to last performed action

    def push(self, action: Dict):
        # drop any redoable actions
        if self.index < len(self.stack) - 1:
            self.stack = self.stack[:self.index+1]
        self.stack.append(action)
        if len(self.stack) > self.capacity:
            self.stack.pop(0)
        else:
            self.index += 1

    def can_undo(self) -> bool:
        return self.index >= 0

    def can_redo(self) -> bool:
        return self.index < len(self.stack) - 1

    def undo(self) -> Optional[Dict]:
        if not self.can_undo():
            return None
        action = self.stack[self.index]
        self.index -= 1
        return action

    def redo(self) -> Optional[Dict]:
        if not self.can_redo():
            return None
        self.index += 1
        action = self.stack[self.index]
        return action

# -------------------------
# ImageCanvas (UI)
# -------------------------
class ImageCanvas(tk.Canvas):
    HANDLE_R = 6
    PROX_TOLERANCE = 8  # proximity tolerance for detecting clicks near edges/corners

    def __init__(self, parent, width, height,
                 on_rect_finalized, on_modify_start, on_rect_modified,
                 on_delete_request, on_select_request):
        super().__init__(parent, bg="#202225", width=width, height=height, highlightthickness=0)
        self.pack(fill=tk.BOTH, expand=True)

        # image
        self.photo: Optional[ImageTk.PhotoImage] = None
        self.image_id: Optional[int] = None
        self.img_w = width
        self.img_h = height
        self.img_path: Optional[str] = None

        # callbacks
        self.on_rect_finalized = on_rect_finalized
        self.on_modify_start = on_modify_start
        self.on_rect_modified = on_rect_modified
        self.on_delete_request = on_delete_request
        self.on_select_request = on_select_request

        # state
        self.mode = 'idle'  # idle | drawing | moving | resizing
        self.start_x = None
        self.start_y = None
        self.temp_rect_id = None
        self.active_rect = None
        self.active_handle = None

        # registry: rect_id -> {'text': id, 'handles': [ids], 'tag': str}
        self.registry: Dict[int, Dict] = {}

        # selection
        self.selected_rect: Optional[int] = None

        # bindings
        self.bind("<Button-1>", self.on_mouse_down)
        self.bind("<B1-Motion>", self.on_mouse_drag)
        self.bind("<ButtonRelease-1>", self.on_mouse_up)
        self.bind("<Double-Button-1>", self.on_double_click)
        self.bind("<Configure>", self.on_configure)

    # -- image handling --
    def show_image(self, path: str, width: int, height: int):
        self.img_path = path
        self.img_w, self.img_h = width, height
        img = Image.open(path).resize((width, height))
        self.photo = ImageTk.PhotoImage(img)
        self.delete("all")
        self.registry.clear()
        self.image_id = self.create_image(0, 0, anchor=tk.NW, image=self.photo)

    def on_configure(self, event):
        # higher-level app will ask to redraw with new size
        pass

    # -- drawing primitives --
    def _create_handles(self, x1, y1, x2, y2) -> List[int]:
        r = self.HANDLE_R
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        pts = [
            (x1, y1), (cx, y1), (x2, y1),
            (x2, cy), (x2, y2), (cx, y2),
            (x1, y2), (x1, cy)
        ]  # TL, TM, TR, MR, BR, BM, BL, ML
        ids = []
        for (hx, hy) in pts:
            hid = self.create_oval(hx - r, hy - r, hx + r, hy + r, fill="#1abc9c", outline="")
            ids.append(hid)
        return ids

    def _move_handles_to(self, rect_id: int, x1, y1, x2, y2):
        r = self.HANDLE_R
        cx = (x1 + x2) / 2
        cy = (y1 + y2) / 2
        pts = [
            (x1, y1), (cx, y1), (x2, y1),
            (x2, cy), (x2, y2), (cx, y2),
            (x1, y2), (x1, cy)
        ]
        for hid, (hx, hy) in zip(self.registry[rect_id]['handles'], pts):
            self.coords(hid, hx - r, hy - r, hx + r, hy + r)

    def draw_rect(self, x1, y1, x2, y2, tag: str) -> int:
        rect_id = self.create_rectangle(x1, y1, x2, y2, outline="#4aa3ff", width=2, tags=("rect",))
        text_id = self.create_text(min(x1, x2) + 6, min(y1, y2) + 6, text=tag, fill="#FF4500", anchor=tk.NW, font=("David", 16))
        handles = self._create_handles(x1, y1, x2, y2)
        self.registry[rect_id] = {'text': text_id, 'handles': handles, 'tag': tag}
        return rect_id

    def _rect_for_handle(self, handle_id: int) -> Optional[int]:
        for rid, meta in self.registry.items():
            if handle_id in meta['handles']:
                return rid
        return None

    def _rect_coords(self, rid: int) -> Tuple[float, float, float, float]:
        return tuple(self.coords(rid))

    def _set_rect_coords(self, rid: int, x1: float, y1: float, x2: float, y2: float):
        self.coords(rid, x1, y1, x2, y2)
        tx = min(x1, x2) + 6
        ty = min(y1, y2) + 6
        self.coords(self.registry[rid]['text'], tx, ty)
        self._move_handles_to(rid, x1, y1, x2, y2)

    # proximity-aware hit detection
    def _hit_which(self, x: int, y: int) -> Tuple[str, Optional[int]]:
        """Return ('handle', hid) | ('rect', rid) | ('none', None)
        This uses proximity tolerance to decide if click near edge/corner.
        """
        tol = self.PROX_TOLERANCE
        # first check handles exactly (they are relatively large)
        for rid, meta in self.registry.items():
            for hid in meta['handles']:
                x1, y1, x2, y2 = self.coords(hid)
                if x1 - 0 <= x <= x2 + 0 and y1 - 0 <= y <= y2 + 0:
                    return 'handle', hid
        # then check proximity to rect edges/corners
        for rid, meta in self.registry.items():
            x1, y1, x2, y2 = self._rect_coords(rid)
            left, right = min(x1, x2), max(x1, x2)
            top, bottom = min(y1, y2), max(y1, y2)
            # corners distance
            corners = [(left, top), (right, top), (right, bottom), (left, bottom)]
            for cx, cy in corners:
                if (abs(cx - x) <= tol) and (abs(cy - y) <= tol):
                    # choose nearest corner handle
                    # find handle id that matches that corner (TL=0, TR=2, BR=4, BL=6)
                    idx_map = {(left, top): 0, ( (left+right)/2, top ):1, (right, top):2,
                               (right, (top+bottom)/2):3, (right, bottom):4, ((left+right)/2, bottom):5,
                               (left, bottom):6, (left, (top+bottom)/2):7}
                    # determine corner index
                    # small search:
                    best = None
                    best_idx = None
                    for i, (hx, hy) in enumerate([(left,top), ((left+right)/2,top), (right,top), (right,(top+bottom)/2),
                                                  (right,bottom), ((left+right)/2,bottom), (left,bottom), (left,(top+bottom)/2)]):
                        d = abs(hx-x) + abs(hy-y)
                        if best is None or d < best:
                            best = d
                            best_idx = i
                    if best_idx is not None:
                        hid = self.registry[rid]['handles'][best_idx]
                        return 'handle', hid
            # edges proximity (top,bottom,left,right)
            if top - tol <= y <= top + tol and left - tol <= x <= right + tol:
                # top edge - choose TM handle (index 1)
                return 'handle', self.registry[rid]['handles'][1]
            if bottom - tol <= y <= bottom + tol and left - tol <= x <= right + tol:
                return 'handle', self.registry[rid]['handles'][5]
            if left - tol <= x <= left + tol and top - tol <= y <= bottom + tol:
                return 'handle', self.registry[rid]['handles'][7]
            if right - tol <= x <= right + tol and top - tol <= y <= bottom + tol:
                return 'handle', self.registry[rid]['handles'][3]
            # interior (select/move)
            if left < x < right and top < y < bottom:
                return 'rect', rid
        return 'none', None

    # mouse events
    def on_mouse_down(self, event):
        kind, hid = self._hit_which(event.x, event.y)
        self.start_x, self.start_y = event.x, event.y
        if kind == 'handle' and hid is not None:
            self.mode = 'resizing'
            self.active_handle = hid
            self.active_rect = self._rect_for_handle(hid)
            # notify controller to store start state
            if self.active_rect is not None:
                self.on_modify_start(self.active_rect)
        elif kind == 'rect' and hid is not None:
            self.mode = 'moving'
            self.active_rect = hid
            # highlight selection
            self.select_rect(hid)
            # notify controller to store start state
            self.on_modify_start(hid)
        else:
            # start drawing
            self.mode = 'drawing'
            self.temp_rect_id = self.create_rectangle(event.x, event.y, event.x, event.y,
                                                      outline="#ff4757", dash=(3, 2))

    def on_mouse_drag(self, event):
        if self.mode == 'drawing' and self.temp_rect_id:
            self.coords(self.temp_rect_id, self.start_x, self.start_y, event.x, event.y)
        elif self.mode == 'moving' and self.active_rect:
            dx = event.x - self.start_x
            dy = event.y - self.start_y
            x1, y1, x2, y2 = self._rect_coords(self.active_rect)
            self._set_rect_coords(self.active_rect, x1 + dx, y1 + dy, x2 + dx, y2 + dy)
            self.start_x, self.start_y = event.x, event.y
        elif self.mode == 'resizing' and self.active_rect and self.active_handle:
            meta = self.registry[self.active_rect]
            handles = meta['handles']
            idx = handles.index(self.active_handle)  # 0..7
            x1, y1, x2, y2 = self._rect_coords(self.active_rect)
            left, right = min(x1, x2), max(x1, x2)
            top, bottom = min(y1, y2), max(y1, y2)
            x, y = event.x, event.y
            if idx == 0:  # TL
                left, top = x, y
            elif idx == 1:  # TM
                top = y
            elif idx == 2:  # TR
                right, top = x, y
            elif idx == 3:  # MR (right edge)
                right = x
            elif idx == 4:  # BR
                right, bottom = x, y
            elif idx == 5:  # BM
                bottom = y
            elif idx == 6:  # BL
                left, bottom = x, y
            elif idx == 7:  # ML (left edge)
                left = x
            # clamp and min-size
            eps = 3
            if right - left < eps:
                right = left + eps
            if bottom - top < eps:
                bottom = top + eps
            left = max(0, min(left, self.img_w))
            right = max(0, min(right, self.img_w))
            top = max(0, min(top, self.img_h))
            bottom = max(0, min(bottom, self.img_h))
            self._set_rect_coords(self.active_rect, left, top, right, bottom)

    def on_mouse_up(self, event):
        if self.mode == 'drawing' and self.temp_rect_id:
            x1, y1, x2, y2 = self.coords(self.temp_rect_id)
            self.delete(self.temp_rect_id)
            self.temp_rect_id = None
            self.mode = 'idle'
            # let controller handle creation (it will add to model and draw permanent)
            self.on_rect_finalized(x1, y1, x2, y2)
        elif self.mode in ('moving', 'resizing') and self.active_rect:
            x1, y1, x2, y2 = self._rect_coords(self.active_rect)
            rid = self.active_rect
            self.mode = 'idle'
            self.active_rect = None
            self.active_handle = None
            # notify controller with final coords
            self.on_rect_modified(rid, x1, y1, x2, y2)
        else:
            self.mode = 'idle'

    def on_double_click(self, event):
        kind, hid = self._hit_which(event.x, event.y)
        if kind == 'rect' and hid is not None:
            # ask controller to delete (controller will capture state and then call back to delete visuals)
            self.on_delete_request(hid)
        elif kind == 'handle' and hid is not None:
            rid = self._rect_for_handle(hid)
            if rid is not None:
                self.on_delete_request(rid)

    # selection visuals
    def select_rect(self, rect_id: Optional[int]):
        # unselect previous
        if self.selected_rect and self.selected_rect in self.registry:
            self.itemconfig(self.selected_rect, outline="#4aa3ff")
        self.selected_rect = rect_id
        if rect_id and rect_id in self.registry:
            self.itemconfig(rect_id, outline="#f1c40f")  # highlight
            # also notify controller about selection
            self.on_select_request(rect_id)

    def _delete_rect_visual(self, rect_id: int):
        if rect_id in self.registry:
            meta = self.registry.pop(rect_id)
            self.delete(rect_id)
            self.delete(meta['text'])
            for hid in meta['handles']:
                self.delete(hid)
            if self.selected_rect == rect_id:
                self.selected_rect = None

# -------------------------
# Main App (controller)
# -------------------------
class ImageLabelingApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Image Labeling App")
        self.root.geometry("1250x760")

        # layout: left tags, center canvas with top status, right listbox
        self.left_panel = tk.Frame(root, width=190, bg="#2c2f33")
        self.left_panel.pack(side=tk.LEFT, fill=tk.Y)

        self.right_panel = tk.Frame(root, width=260, bg="#2c2f33")
        self.right_panel.pack(side=tk.RIGHT, fill=tk.Y)

        center = tk.Frame(root, bg="#23272a")
        center.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        topbar = tk.Frame(center, height=36, bg="#2c2f33")
        topbar.pack(side=tk.TOP, fill=tk.X)
        self.status_label = tk.Label(topbar, text="", fg="#bdc3c7", bg="#2c2f33")
        self.status_label.pack(side=tk.LEFT, padx=10)

        # canvas
        self.canvas = ImageCanvas(center, 900, 680,
                                  on_rect_finalized=self.on_new_rect,
                                  on_modify_start=self.on_modify_start,
                                  on_rect_modified=self.on_rect_modified,
                                  on_delete_request=self.request_delete_rect,
                                  on_select_request=self.on_select_request)
        # tags (left)
        tk.Label(self.left_panel, text="Tags", fg="#ecf0f1", bg="#2c2f33", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 4))
        self.tag_var = tk.StringVar(value="Object")
        self.tags = ["Object", "Person", "Car", "Dog", "Cat"]
        for t in self.tags:
            rb = tk.Radiobutton(self.left_panel, text=t, variable=self.tag_var, value=t,
                                fg="#ecf0f1", bg="#2c2f33", selectcolor="#34495e", activebackground="#2c2f33",
                                command=self.on_tag_change_by_user)
            rb.pack(anchor=tk.W, padx=12)

        # right: image list
        tk.Label(self.right_panel, text="Images", fg="#ecf0f1", bg="#2c2f33", font=("Segoe UI", 12, "bold")).pack(anchor=tk.W, padx=10, pady=(10, 4))
        self.listbox = tk.Listbox(self.right_panel, activestyle='none')
        self.scroll = tk.Scrollbar(self.right_panel, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=self.scroll.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,0), pady=(0,10))
        self.scroll.pack(side=tk.RIGHT, fill=tk.Y, padx=(0,10), pady=(0,10))
        self.listbox.bind('<<ListboxSelect>>', self.on_list_select)

        # menu
        menubar = tk.Menu(root)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Open Folder", command=self.load_directory)
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=root.quit)
        menubar.add_cascade(label="File", menu=file_menu)
        root.config(menu=menubar)

        # keybindings for navigation and undo/redo
        root.bind('<Right>', lambda e: self.next_image())
        root.bind('<Left>', lambda e: self.prev_image())
        # Undo/Redo
        root.bind_all('<Control-z>', lambda e: self._undo())
        root.bind_all('<Control-y>', lambda e: self._redo())
        root.bind_all('<Control-Shift-Z>', lambda e: self._redo())
        # mac command support
        root.bind_all('<Command-z>', lambda e: self._undo())
        root.bind_all('<Command-Shift-Z>', lambda e: self._redo())

        # data structures
        self.rect_manager = RectManager()
        self.images: List[str] = []
        self.image_index = 0
        self._canvas_size = (self.canvas.winfo_width(), self.canvas.winfo_height())

        # mapping between canvas rect id and rect manager uid
        self.rid_to_uid: Dict[int, int] = {}
        self.uid_to_rid: Dict[int, int] = {}

        # selection info
        self.selected_uid: Optional[int] = None

        # action stack for undo/redo
        self.actions = ActionStack(capacity=30)
        # temporarily store start state for move/resize
        self._pending_modify_start: Dict[int, Dict] = {}  # rid -> {'cx','cy','w','h','tag'}

        # respond to canvas resize
        self.canvas.bind('<Configure>', self._on_canvas_configure)

    # UI helpers
    def _on_canvas_configure(self, event):
        new_size = (event.width, event.height)
        if new_size != self._canvas_size:
            self._canvas_size = new_size
            if self.images:
                self._show_current_image()

    def _update_status(self):
        if not self.images:
            self.status_label.config(text="No folder loaded")
        else:
            fname = os.path.basename(self.images[self.image_index])
            self.status_label.config(text=f"{self.image_index+1}/{len(self.images)}: {fname}")

    def load_directory(self):
        folder = filedialog.askdirectory()
        if not folder:
            return
        self.images = [
            os.path.join(folder, f) for f in sorted(os.listdir(folder))
            if f.lower().endswith((".jpg", ".jpeg", ".png", ".bmp"))
        ]
        self.image_index = 0
        self.listbox.delete(0, tk.END)
        for p in self.images:
            self.listbox.insert(tk.END, os.path.basename(p))
        if self.images:
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)
        self._show_current_image()

    def on_list_select(self, event):
        sel = self.listbox.curselection()
        if sel:
            idx = sel[0]
            if 0 <= idx < len(self.images):
                self.image_index = idx
                self._show_current_image()

    def prev_image(self):
        if not self.images:
            return
        self.image_index = (self.image_index - 1) % len(self.images)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.image_index)
        self.listbox.activate(self.image_index)
        self._show_current_image()

    def next_image(self):
        if not self.images:
            return
        self.image_index = (self.image_index + 1) % len(self.images)
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(self.image_index)
        self.listbox.activate(self.image_index)
        self._show_current_image()

    def _txt_path_for(self, img_path: str) -> str:
        base, _ = os.path.splitext(img_path)
        return base + ".txt"

    def _show_current_image(self):
        img_path = self.images[self.image_index]
        txt_path = self._txt_path_for(img_path)
        cw, ch = self._canvas_size
        cw = max(50, cw)
        ch = max(50, ch)
        self.canvas.show_image(img_path, cw, ch)
        if txt_path not in self.rect_manager.rectangles:
            self.rect_manager.load_from_txt(txt_path)
        # draw fresh and reset maps
        self.rid_to_uid.clear()
        self.uid_to_rid.clear()
        # draw each rect
        for r in self.rect_manager.rectangles.get(txt_path, []):
            x1, y1, x2, y2 = RectManager.cxcywh_to_xyxy(r['cx'], r['cy'], r['w'], r['h'], cw, ch)
            rid = self.canvas.draw_rect(x1, y1, x2, y2, r['tag'])
            self.rid_to_uid[rid] = r['uid']
            self.uid_to_rid[r['uid']] = rid
        self._update_status()

    # -------------------------
    # Callbacks from canvas
    # -------------------------
    def on_new_rect(self, x1, y1, x2, y2):
        if not self.images:
            return
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        cw, ch = self._canvas_size
        cx, cy, w, h = RectManager.xyxy_to_cxcywh(x1, y1, x2, y2, cw, ch)
        tag = self.tag_var.get()
        uid = self.rect_manager.add_rect(txt, tag, cx, cy, w, h)
        rid = self.canvas.draw_rect(x1, y1, x2, y2, tag)
        self.rid_to_uid[rid] = uid
        self.uid_to_rid[uid] = rid
        # push create action
        action = {'type': 'CREATE', 'txt': txt, 'uid': uid, 'rect': {'tag': tag, 'cx': cx, 'cy': cy, 'w': w, 'h': h}}
        self.actions.push(action)
        self.rect_manager.save_to_txt(txt)

    def on_modify_start(self, rect_canvas_id: int):
        # store start normalized coords for undo
        if rect_canvas_id not in self.rid_to_uid:
            return
        uid = self.rid_to_uid[rect_canvas_id]
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        r = self.rect_manager.get_rect_by_uid(txt, uid)
        if r is None:
            return
        # store copy
        self._pending_modify_start[rect_canvas_id] = {'tag': r['tag'], 'cx': r['cx'], 'cy': r['cy'], 'w': r['w'], 'h': r['h']}

    def on_rect_modified(self, rect_canvas_id: int, x1, y1, x2, y2):
        # called at mouse_up after move or resize
        if rect_canvas_id not in self.rid_to_uid:
            return
        uid = self.rid_to_uid[rect_canvas_id]
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        cw, ch = self._canvas_size
        cx, cy, w, h = RectManager.xyxy_to_cxcywh(x1, y1, x2, y2, cw, ch)
        # get start state
        start = self._pending_modify_start.pop(rect_canvas_id, None)
        if start:
            # push action with before/after coords
            action = {'type': 'MODIFY', 'txt': txt, 'uid': uid,
                      'before': {'tag': start['tag'], 'cx': start['cx'], 'cy': start['cy'], 'w': start['w'], 'h': start['h']},
                      'after': {'tag': start['tag'], 'cx': cx, 'cy': cy, 'w': w, 'h': h}}
            self.actions.push(action)
        # update model and save
        self.rect_manager.update_rect(txt, uid, cx, cy, w, h)
        self.rect_manager.save_to_txt(txt)

    def request_delete_rect(self, rect_canvas_id: int):
        # When user double-clicks, canvas asks controller to delete.
        if rect_canvas_id not in self.rid_to_uid:
            return
        uid = self.rid_to_uid[rect_canvas_id]
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        r = self.rect_manager.get_rect_by_uid(txt, uid)
        if r is None:
            return
        # push delete action with full rect info so we can undo
        action = {'type': 'DELETE', 'txt': txt, 'uid': uid, 'rect': {'tag': r['tag'], 'cx': r['cx'], 'cy': r['cy'], 'w': r['w'], 'h': r['h']}}
        self.actions.push(action)
        # delete from model
        self.rect_manager.delete_rect(txt, uid)
        self.rect_manager.save_to_txt(txt)
        # delete visuals
        self.canvas._delete_rect_visual(rect_canvas_id)
        # drop maps
        self.rid_to_uid.pop(rect_canvas_id, None)
        self.uid_to_rid.pop(uid, None)

    def on_select_request(self, rect_canvas_id: int):
        # set currently selected UID (when user clicks a rect)
        if rect_canvas_id not in self.rid_to_uid:
            self.selected_uid = None
            return
        uid = self.rid_to_uid[rect_canvas_id]
        self.selected_uid = uid
        # set tag_var to reflect selected rect's tag (but do not trigger tag-change action)
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        r = self.rect_manager.get_rect_by_uid(txt, uid)
        if r:
            # temporarily unbind trace action and set value
            self.tag_var.set(r['tag'])

    # tag change by user via Radiobuttons
    def on_tag_change_by_user(self):
        if self.selected_uid is None:
            return
        new_tag = self.tag_var.get()
        img = self.images[self.image_index]
        txt = self._txt_path_for(img)
        r = self.rect_manager.get_rect_by_uid(txt, self.selected_uid)
        if not r:
            return
        old_tag = r['tag']
        if old_tag == new_tag:
            return
        # apply change to model
        self.rect_manager.update_tag(txt, self.selected_uid, new_tag)
        # update canvas text
        rid = self.uid_to_rid.get(self.selected_uid)
        if rid:
            text_id = self.canvas.registry[rid]['text']
            self.canvas.itemconfig(text_id, text=new_tag)
            self.canvas.registry[rid]['tag'] = new_tag
        # push action
        action = {'type': 'TAG_CHANGE', 'txt': txt, 'uid': self.selected_uid, 'before': old_tag, 'after': new_tag}
        self.actions.push(action)
        self.rect_manager.save_to_txt(txt)

    # -------------------------
    # Undo/Redo implementation
    # -------------------------
    def _undo(self):
        act = self.actions.undo()
        if not act:
            return
        typ = act['type']
        if typ == 'CREATE':
            # remove created rect (act contains uid)
            uid = act['uid']
            txt = act['txt']
            # find rid if exists
            rid = self.uid_to_rid.get(uid)
            if rid:
                self.canvas._delete_rect_visual(rid)
                self.rid_to_uid.pop(rid, None)
                self.uid_to_rid.pop(uid, None)
            # remove from model
            self.rect_manager.delete_rect(txt, uid)
            self.rect_manager.save_to_txt(txt)
        elif typ == 'DELETE':
            # restore deleted rect (act carries rect data including uid)
            uid = act['uid']
            txt = act['txt']
            r = act['rect']
            # add back to model with same uid
            self.rect_manager.add_rect(txt, r['tag'], r['cx'], r['cy'], r['w'], r['h'], uid=uid)
            # draw visuals
            x1, y1, x2, y2 = RectManager.cxcywh_to_xyxy(r['cx'], r['cy'], r['w'], r['h'], *self._canvas_size)
            rid = self.canvas.draw_rect(x1, y1, x2, y2, r['tag'])
            self.rid_to_uid[rid] = uid
            self.uid_to_rid[uid] = rid
            self.rect_manager.save_to_txt(txt)
        elif typ == 'MODIFY':
            uid = act['uid']; txt = act['txt']
            before = act['before']
            # update model
            self.rect_manager.update_rect(txt, uid, before['cx'], before['cy'], before['w'], before['h'])
            # update visuals
            rid = self.uid_to_rid.get(uid)
            if rid:
                x1, y1, x2, y2 = RectManager.cxcywh_to_xyxy(before['cx'], before['cy'], before['w'], before['h'], *self._canvas_size)
                self.canvas._set_rect_coords(rid, x1, y1, x2, y2)
            self.rect_manager.save_to_txt(txt)
        elif typ == 'TAG_CHANGE':
            uid = act['uid']; txt = act['txt']
            before = act['before']
            # update model
            self.rect_manager.update_tag(txt, uid, before)
            # update visuals
            rid = self.uid_to_rid.get(uid)
            if rid:
                text_id = self.canvas.registry[rid]['text']
                self.canvas.itemconfig(text_id, text=before)
                self.canvas.registry[rid]['tag'] = before
            self.rect_manager.save_to_txt(txt)

    def _redo(self):
        act = self.actions.redo()
        if not act:
            return
        typ = act['type']
        if typ == 'CREATE':
            uid = act['uid']; txt = act['txt']; r = act['rect']
            # add back to model with same uid
            self.rect_manager.add_rect(txt, r['tag'], r['cx'], r['cy'], r['w'], r['h'], uid=uid)
            x1, y1, x2, y2 = RectManager.cxcywh_to_xyxy(r['cx'], r['cy'], r['w'], r['h'], *self._canvas_size)
            rid = self.canvas.draw_rect(x1, y1, x2, y2, r['tag'])
            self.rid_to_uid[rid] = uid
            self.uid_to_rid[uid] = rid
            self.rect_manager.save_to_txt(txt)
        elif typ == 'DELETE':
            uid = act['uid']; txt = act['txt']
            # find rid and remove
            rid = self.uid_to_rid.get(uid)
            if rid:
                self.canvas._delete_rect_visual(rid)
                self.rid_to_uid.pop(rid, None)
                self.uid_to_rid.pop(uid, None)
            self.rect_manager.delete_rect(txt, uid)
            self.rect_manager.save_to_txt(txt)
        elif typ == 'MODIFY':
            uid = act['uid']; txt = act['txt']; after = act['after']
            self.rect_manager.update_rect(txt, uid, after['cx'], after['cy'], after['w'], after['h'])
            rid = self.uid_to_rid.get(uid)
            if rid:
                x1, y1, x2, y2 = RectManager.cxcywh_to_xyxy(after['cx'], after['cy'], after['w'], after['h'], *self._canvas_size)
                self.canvas._set_rect_coords(rid, x1, y1, x2, y2)
            self.rect_manager.save_to_txt(txt)
        elif typ == 'TAG_CHANGE':
            uid = act['uid']; txt = act['txt']; after = act['after']
            self.rect_manager.update_tag(txt, uid, after)
            rid = self.uid_to_rid.get(uid)
            if rid:
                text_id = self.canvas.registry[rid]['text']
                self.canvas.itemconfig(text_id, text=after)
                self.canvas.registry[rid]['tag'] = after
            self.rect_manager.save_to_txt(txt)

# -------------------------
# Entry point
# -------------------------
if __name__ == "__main__":
    root = tk.Tk()
    app = ImageLabelingApp(root)
    root.mainloop()
