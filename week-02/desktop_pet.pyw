"""데스크톱 키보드 펫

바탕화면 위에 떠서, 키보드를 치거나 마우스를 누르면 프레임을 바꿔 가며 연주하는 펫.
- 펫 클릭: 점프하며 한마디
- 펫 끌기: 옮기기 (놓으면 작업 표시줄 위로 떨어짐)
- 펫 오른쪽 클릭: 설정 메뉴 (캐릭터, 크기, 소리, 반응 켜기/끄기, 잠들기, 종료)
누른 키가 무엇인지는 저장하지 않고, 눌렸다는 것만 알아챈다.
"""
import array
import ctypes
import json
import math
import os
import random
import struct
import time
import tkinter as tk
import wave
import winsound
from ctypes import wintypes

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '.pet-data')        # 설정과 소리 파일 (GitHub 에 안 올라감)
SND = os.path.join(DATA, 'sounds')
SETTINGS = os.path.join(DATA, 'settings.json')
os.makedirs(SND, exist_ok=True)

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)  # 화면 배율이 커도 선명하게
except Exception:
    pass
user32 = ctypes.windll.user32
user32.GetAsyncKeyState.restype = ctypes.c_short

KEY = '#010203'   # 이 색은 투명하게 보인다 (그림 테두리가 검정이라 가장자리가 자연스럽다)
TOP = 60          # 그림 위쪽 여유 (점프, 떠오르는 글자)
SLEEP_AFTER = 10  # 이 시간(초) 동안 아무 입력이 없으면 잠든다

# 그림 한 장에 2×2 프레임: 0 두 손 듦 · 1 왼손 침 · 2 오른손 침 · 3 두 손 침
PETS = {
    'dog':      dict(name='🐶 강아지',     file='dog.png',      tap='xylo',   voice='bark',  word='멍!'),
    # 고양이 그림은 오른손 칸도 왼손으로 치고 있어서, 왼손 그림을 좌우로 뒤집어 오른손으로 쓴다
    'cat':      dict(name='🐱 고양이',     file='cat.png',      tap='drum',   voice='meow',  word='야옹~', mirror_right=True),
}
SIZES = {'작게': 4, '보통': 3, '크게': 2}            # 그림을 몇 분의 1로 줄일지
VOLUMES = {'크게': 1.0, '보통': 0.55, '작게': 0.25, '끄기': 0}
DEFAULT = dict(pet='dog', size='보통', volume='보통', listen=True, sleep=True, count=0, x=None, y=None)
COLORS = ['#ff5d8f', '#ff9f1c', '#2ec4b6', '#3a86ff', '#8338ec', '#06d6a0', '#ef476f']


# ---------- 소리 만들기 (파일 없이 직접 합성) ----------
RATE = 22050


def sweep(dur, freq, wave_fn, env):
    out, ph = [], 0.0
    for i in range(int(RATE * dur)):
        t = i / RATE
        ph += 2 * math.pi * freq(t) / RATE
        out.append(wave_fn(ph) * env(t))
    return out


def saw(ph):
    return (ph / (2 * math.pi)) % 1 * 2 - 1


def square(ph):
    return 1.0 if math.sin(ph) >= 0 else -1.0


def lowpass(xs, a):
    y, out = 0.0, []
    for x in xs:
        y += a * (x - y)
        out.append(y)
    return out


def synth(kind, f):
    if kind == 'xylo':    # 실로폰: 맑은 소리 + 높은 배음
        a = sweep(0.45, lambda t: f, math.sin, lambda t: 0.7 * math.exp(-t * 9))
        b = sweep(0.45, lambda t: f * 3.9, math.sin, lambda t: 0.2 * math.exp(-t * 40))
        return [x + y for x, y in zip(a, b)]
    if kind == 'drum':    # 드럼: 둥 + 치익
        body = sweep(0.22, lambda t: 55 + (65 + f * 0.08) * math.exp(-t * 25), math.sin,
                     lambda t: 0.8 * math.exp(-t * 14))
        prev, out = 0.0, []
        for i, x in enumerate(body):
            r = random.uniform(-1, 1)
            out.append(x + 0.25 * (r - prev) * math.exp(-i / RATE * 35))
            prev = r
        return out
    if kind == 'button':  # 버튼: 삑 + 딸깍
        a = sweep(0.12, lambda t: f, square, lambda t: 0.25 * math.exp(-t * 25))
        b = sweep(0.12, lambda t: max(300, 900 - 6000 * t), math.sin, lambda t: 0.5 * math.exp(-t * 120))
        return [x + y for x, y in zip(a, b)]
    if kind == 'bark':
        one = lambda k: lowpass(sweep(0.16, lambda t: 420 * k * 0.45 ** (t / 0.16), saw,
                                      lambda t: min(1, t / 0.01) * math.exp(-t * 12)), 0.3)
        return one(1.0) + [0.0] * int(RATE * 0.04) + one(1.1)
    if kind == 'meow':
        freq = lambda t: 430 + 290 * t / 0.12 if t < 0.12 else 720 - 240 * (t - 0.12) / 0.38
        return lowpass(sweep(0.5, freq, saw, lambda t: 0.9 * min(1, t / 0.05) * (1 - t / 0.5) ** 1.5), 0.2)
    if kind == 'alarm':
        return sweep(0.6, lambda t: 880 if int(t / 0.15) % 2 == 0 else 660, square,
                     lambda t: 0.3 * (1 if t < 0.5 else (0.6 - t) / 0.1))
    if kind == 'chirp':
        return sweep(0.16, lambda t: min(1300, 600 * (1300 / 600) ** (t / 0.12)), math.sin,
                     lambda t: 0.6 * min(1, t / 0.005) * math.exp(-t * 15))
    return []


def pent(n):  # 도레미솔라 음계
    steps = [0, 2, 4, 7, 9]
    return 261.63 * 2 ** ((12 * (n // 5) + steps[n % 5]) / 12)


def sound_path(kind, note, vol):
    return os.path.join(SND, f'{kind}_{note}_{int(vol * 100)}.wav')


def make_sound(kind, note, vol):
    path = sound_path(kind, note, vol)
    if not os.path.exists(path):
        xs = synth(kind, pent(note))
        data = array.array('h', (int(max(-1.0, min(1.0, x * vol)) * 32000) for x in xs))
        with wave.open(path, 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(RATE)
            w.writeframes(data.tobytes())
    return path


# ---------- 키 → 손, 음, 글자 ----------
ROWS = ['ZXCVBNM', 'ASDFGHJKL', 'QWERTYUIOP', '1234567890']
VK_MOUSE = 0x01
WATCH = [VK_MOUSE, 0x20, 0x0D, 0x08] + list(range(0x30, 0x3A)) + list(range(0x41, 0x5B))


def key_info(vk):
    c = chr(vk) if 0x30 <= vk <= 0x5A else ''
    for r, row in enumerate(ROWS):
        if c and c in row:
            col = row.index(c)
            return dict(side='L' if col < 5 else 'R', note=col + r * 3, label=c)
    if vk == 0x20:
        return dict(side='B', note=5, label='♪')
    return dict(side=None, note=random.randint(3, 10), label={0x0D: '↵', 0x08: '←'}.get(vk, '♪'))


def read_png(path):
    """그림에 붙은 부가 정보(caBX 등)가 있으면 Tk 9 가 크기를 잘못 읽어서, 그림 데이터만 골라 읽는다.
    파일은 바꾸지 않는다."""
    with open(path, 'rb') as f:
        d = f.read()
    out, i = [d[:8]], 8
    while i < len(d):
        n = struct.unpack('>I', d[i:i + 4])[0]
        if d[i + 4:i + 8] in (b'IHDR', b'PLTE', b'tRNS', b'IDAT', b'IEND'):
            out.append(d[i:i + 12 + n])
        i += 12 + n
    return b''.join(out)


def work_area():
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r.left, r.top, r.right, r.bottom


def load_settings():
    s = dict(DEFAULT)
    try:
        with open(SETTINGS, encoding='utf-8') as f:
            s.update(json.load(f))
    except Exception:
        pass
    if s['pet'] not in PETS: s['pet'] = 'dog'
    if s['size'] not in SIZES: s['size'] = '보통'
    if s['volume'] not in VOLUMES: s['volume'] = '보통'
    return s


class Pet:
    def __init__(self):
        self.s = load_settings()
        r = self.root = tk.Tk()
        r.title('키보드 펫')
        r.overrideredirect(True)
        r.attributes('-topmost', True)
        r.attributes('-transparentcolor', KEY)
        r.configure(bg=KEY)
        self.cv = tk.Canvas(r, bg=KEY, highlightthickness=0, bd=0, cursor='hand2')
        self.cv.pack()
        self.img_item = self.cv.create_image(0, TOP, anchor='nw')
        # 거의 투명한 점은 완전히 투명하게 (안 그러면 펫 둘레에 검은 점으로 보인다)
        r.tk.eval('''proc cleanAlpha {img thr} {
            set w [image width $img]; set h [image height $img]
            for {set y 0} {$y < $h} {incr y} { for {set x 0} {$x < $w} {incr x} {
                set a [lindex [$img get $x $y -withalpha] 3]
                if {$a > 0 && $a < $thr} { $img transparency set $x $y 1 }
            } }
        }''')

        self.sheets = {}
        self.ch = {}          # 프레임 애니메이션 채널
        self.parts = []       # 떠오르는 글자
        self.keys_down = set()
        self.sleeping = False
        self.last_input = time.perf_counter()
        self.combo, self.last_tap, self.alt, self.next_z = 0, 0.0, 0, 0.0
        self.drag, self.moved, self.pet_press = None, False, 0.0
        self.falling, self.vy = False, 0.0
        self.shown = None
        self.prev = time.perf_counter()
        self.next_save = self.next_top = 0.0
        self.warm = []

        self.build()
        self.place_start()
        self.menu = self.make_menu()
        self.cv.bind('<ButtonPress-1>', self.press)
        self.cv.bind('<B1-Motion>', self.motion)
        self.cv.bind('<ButtonRelease-1>', self.release)
        self.cv.bind('<Button-3>', self.popup)
        r.protocol('WM_DELETE_WINDOW', self.quit)
        self.prepare_sounds()
        self.tick()

    # ---------- 그림 ----------
    def build(self):
        p = PETS[self.s['pet']]
        if p['file'] not in self.sheets:
            self.sheets[p['file']] = tk.PhotoImage(data=read_png(os.path.join(HERE, 'images', p['file'])))
        sheet = self.sheets[p['file']]
        cell, sub = sheet.width() // 2, SIZES[self.s['size']]
        self.frames = []
        for i in range(4):
            flip = i == 2 and p.get('mirror_right')
            src = 1 if flip else i
            x, y = (src % 2) * cell, (src // 2) * cell
            im = tk.PhotoImage()
            im.tk.call(str(im), 'copy', str(sheet), '-from', x, y, x + cell, y + cell,
                       '-subsample', -sub if flip else sub, sub)
            im.tk.call('cleanAlpha', str(im), 160)
            self.frames.append(im)
        self.spr = self.frames[0].width()
        self.W, self.H = self.spr, self.spr + TOP
        self.cv.config(width=self.W, height=self.H)
        self.pad = self.bottom_pad(self.frames[0])
        self.shown = None

    def bottom_pad(self, im):  # 그림 아래 투명한 여백 (작업 표시줄에 딱 붙게)
        w, h = im.width(), im.height()
        for y in range(h - 1, -1, -1):
            for x in range(0, w, 3):
                if not im.transparency_get(x, y):
                    return h - 1 - y
        return 0

    def floor_y(self):
        return work_area()[3] - self.H + self.pad

    def move(self, x, y):
        self.x, self.y = int(x), int(y)
        self.root.geometry(f'{self.W}x{self.H}+{self.x}+{self.y}')

    def place_start(self):
        left, top, right, bottom = work_area()
        x, y = self.s['x'], self.s['y']
        if x is None or y is None or not (left - self.W // 2 < x < right - self.W // 2 and top - TOP < y < bottom):
            x, y = right - self.W - 40, self.floor_y()
        self.move(x, y)

    def home(self):
        left, top, right, bottom = work_area()
        self.falling = False
        self.move(right - self.W - 40, self.floor_y())
        self.save_pos()

    def save_pos(self):
        self.s['x'], self.s['y'] = self.x, self.y
        self.save()

    # ---------- 설정 메뉴 ----------
    def make_menu(self):
        m = tk.Menu(self.root, tearoff=0)
        self.v_pet = tk.StringVar(value=self.s['pet'])
        self.v_size = tk.StringVar(value=self.s['size'])
        self.v_vol = tk.StringVar(value=self.s['volume'])
        self.v_listen = tk.BooleanVar(value=self.s['listen'])
        self.v_sleep = tk.BooleanVar(value=self.s['sleep'])
        m.add_command(label='누른 횟수', state='disabled')
        m.add_separator()
        for label, var, options, cmd in [
            ('캐릭터', self.v_pet, [(k, p['name']) for k, p in PETS.items()], self.change_pet),
            ('크기', self.v_size, [(k, k) for k in SIZES], self.change_size),
            ('소리', self.v_vol, [(k, k) for k in VOLUMES], self.change_volume),
        ]:
            sub = tk.Menu(m, tearoff=0)
            for value, text in options:
                sub.add_radiobutton(label=text, value=value, variable=var, command=cmd)
            m.add_cascade(label=label, menu=sub)
        m.add_checkbutton(label='키보드·마우스에 반응하기', variable=self.v_listen, command=self.change_toggles)
        m.add_checkbutton(label=f'{SLEEP_AFTER}초 가만히 두면 잠들기', variable=self.v_sleep, command=self.change_toggles)
        m.add_separator()
        m.add_command(label='오른쪽 아래로 돌아가기', command=self.home)
        m.add_command(label='종료', command=self.quit)
        return m

    def popup(self, e):
        self.menu.entryconfig(0, label=f'누른 횟수 {self.s["count"]}')
        try:
            self.menu.tk_popup(e.x_root, e.y_root)
        finally:
            self.menu.grab_release()

    def change_pet(self):
        self.s['pet'] = self.v_pet.get()
        self.rebuild()
        self.prepare_sounds()
        self.jump(counted=False)

    def change_size(self):
        self.s['size'] = self.v_size.get()
        self.rebuild()

    def rebuild(self):  # 크기가 바뀌어도 발 위치는 그대로
        old_bottom, old_mid = self.y + self.H, self.x + self.W // 2
        self.build()
        self.move(old_mid - self.W // 2, old_bottom - self.H)
        for item, *_ in self.parts:
            self.cv.delete(item)
        self.parts.clear()
        self.save_pos()

    def change_volume(self):
        self.s['volume'] = self.v_vol.get()
        self.save()
        self.prepare_sounds()
        self.sound(PETS[self.s['pet']]['tap'], 5)

    def change_toggles(self):
        self.s['listen'] = self.v_listen.get()
        self.s['sleep'] = self.v_sleep.get()
        if not self.s['sleep']:
            self.sleeping = False
        self.last_input = time.perf_counter()
        self.save()

    def save(self):
        try:
            with open(SETTINGS, 'w', encoding='utf-8') as f:
                json.dump(self.s, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def quit(self):
        self.save()
        self.root.destroy()

    # ---------- 소리 ----------
    def prepare_sounds(self):  # 처음 누를 때 끊기지 않게 미리 조금씩 만들어 둔다
        vol = VOLUMES[self.s['volume']]
        if vol:
            p = PETS[self.s['pet']]
            self.warm = [(p['voice'], 0), ('chirp', 0)] + [(p['tap'], n) for n in range(19)]

    def sound(self, kind, note=0):
        vol = VOLUMES[self.s['volume']]
        if not vol:
            return
        try:
            winsound.PlaySound(make_sound(kind, note, vol),
                               winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        except Exception:
            pass

    # ---------- 프레임 애니메이션 ----------
    def play(self, name, frames):  # frames: [(바꿀 값, 보여 줄 시간 초), ...]
        self.ch[name] = [frames, 0, time.perf_counter()]

    def step_frames(self, now):
        for k in list(self.ch):
            c = self.ch[k]
            while now - c[2] >= c[0][c[1]][1]:
                c[2] += c[0][c[1]][1]
                c[1] += 1
                if c[1] >= len(c[0]):
                    del self.ch[k]
                    break

    def cur(self, name):
        c = self.ch.get(name)
        return c[0][c[1]][0] if c else {}

    # ---------- 동작 ----------
    def hit_xy(self, side):
        fx = {'L': 0.33, 'R': 0.67, 'B': 0.5}[side]
        return self.spr * fx, TOP + self.spr * 0.6

    def font(self, size):
        return ('Malgun Gothic', max(9, int(size * self.spr / 313)), 'bold')

    def spawn(self, text, x, y, color, size=16, vx=0.0, vy=-1.5, life=0.9):
        item = self.cv.create_text(x, y, text=text, fill=color, font=self.font(size))
        self.parts.append([item, vx, vy, time.perf_counter() + life])

    def wake(self, now):
        self.last_input = now
        if self.sleeping:
            self.sleeping = False
            self.sound('chirp')
            self.spawn('!', self.spr * 0.72, TOP * 0.8, '#ff6b6b', size=22, vy=-0.6)

    def tap(self, info, now):
        self.combo = self.combo + 1 if now - self.last_tap < 0.38 else 1
        self.last_tap = now
        side = info['side']
        if not side:
            side = 'R' if self.alt % 2 else 'L'
            self.alt += 1
        for s in (['L', 'R'] if side == 'B' else [side]):
            self.play('paw' + s, [({'paw' + s: True}, 0.12)])
        self.play('body', [({'y': 3}, 0.06)])
        x, y = self.hit_xy(side)
        self.spawn(info['label'], x + random.uniform(-12, 12), y - 30, random.choice(COLORS),
                   vx=random.uniform(-0.4, 0.4))
        p = PETS[self.s['pet']]
        if self.combo % 10 == 0:  # 콤보 10번마다 신나서 한마디
            self.sound(p['voice'])
            for _ in range(4):
                self.spawn('♥', self.spr * random.uniform(0.3, 0.7), TOP + 10, '#f59ab0', size=18,
                           vx=random.uniform(-1, 1), vy=-1.3)
            self.spawn(f'콤보 {self.combo}!', self.spr / 2, TOP * 0.5, '#ff5d8f', size=18, vy=-0.5, life=1.2)
        else:
            self.sound(p['tap'], info['note'])
        self.add_count()

    def jump(self, counted=True):
        self.play('body', [({'y': 8}, 0.08), ({'y': -24}, 0.08), ({'y': -36}, 0.11),
                           ({'y': -24}, 0.08), ({'y': 6}, 0.08)])
        p = PETS[self.s['pet']]
        self.sound(p['voice'])
        self.spawn(p['word'], self.spr / 2, TOP + 10, '#ff5d8f', size=18, vy=-1.0, life=1.1)
        for _ in range(3):
            self.spawn('♥', self.spr * random.uniform(0.35, 0.65), TOP + 30, '#f59ab0',
                       size=random.randint(14, 20), vx=random.uniform(-1, 1), vy=random.uniform(-2.2, -1.2))
        if counted:
            self.add_count()

    def add_count(self):
        self.s['count'] += 1

    # ---------- 마우스로 펫 만지기 ----------
    def press(self, e):
        self.pet_press = time.perf_counter()
        self.drag = (e.x_root, e.y_root, self.x, self.y)
        self.moved = False
        self.falling = False

    def motion(self, e):
        if not self.drag:
            return
        dx, dy = e.x_root - self.drag[0], e.y_root - self.drag[1]
        if abs(dx) + abs(dy) > 5:
            self.moved = True
        if self.moved:
            self.move(self.drag[2] + dx, self.drag[3] + dy)

    def release(self, e):
        self.drag = None
        now = time.perf_counter()
        if self.moved:
            self.falling, self.vy = True, 0.0
        else:
            self.wake(now)
            self.jump()

    # ---------- 컴퓨터 전체의 키보드·마우스 ----------
    def poll(self, now):
        for vk in WATCH:
            down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if down and vk not in self.keys_down:
                self.keys_down.add(vk)
                if not self.s['listen']:
                    continue
                if vk == VK_MOUSE:
                    self.root.after(60, self.outside_click)  # 펫을 누른 클릭인지 잠깐 기다려 본다
                else:
                    self.wake(now)
                    self.tap(key_info(vk), now)
            elif not down:
                self.keys_down.discard(vk)

    def outside_click(self):
        now = time.perf_counter()
        if now - self.pet_press < 0.3:
            return
        self.wake(now)
        self.tap(dict(side=None, note=random.randint(3, 10), label='♪'), now)

    # ---------- 매 프레임 ----------
    def tick(self):
        now = time.perf_counter()
        dt = min(0.05, now - self.prev)
        self.prev = now
        self.poll(now)
        self.step_frames(now)

        if self.s['sleep'] and not self.sleeping and now - self.last_input > SLEEP_AFTER:
            self.sleeping, self.next_z = True, now
        if self.sleeping and now > self.next_z:
            self.spawn('z', self.spr * 0.72, TOP + self.spr * 0.1, '#9d8df1', size=random.randint(13, 19),
                       vx=0.35, vy=-0.6, life=2.0)
            self.next_z = now + 0.9

        # 이번 프레임의 자세
        p = {'pawL': False, 'pawR': False, 'y': 0}
        if self.sleeping:
            p['pawL'] = p['pawR'] = True                 # 두 손 내려놓고 눈 감은 그림
            p['y'] = 2 if int(now / 0.8) % 2 else 0      # 숨쉬기 2프레임
        else:
            p['y'] = 1 if int(now / 0.5) % 2 else 0
        for name in ('body', 'pawL', 'pawR'):
            p.update(self.cur(name))
        idx = 3 if p['pawL'] and p['pawR'] else 1 if p['pawL'] else 2 if p['pawR'] else 0
        if self.shown != (idx, p['y']):
            self.cv.itemconfig(self.img_item, image=self.frames[idx])
            self.cv.coords(self.img_item, 0, TOP + p['y'])
            self.shown = (idx, p['y'])

        # 떠오르는 글자
        k = dt * 60
        for part in self.parts[:]:
            item, vx, vy, end = part
            if now > end:
                self.cv.delete(item)
                self.parts.remove(part)
            else:
                self.cv.move(item, vx * k, vy * k)

        # 놓으면 떨어지기
        if self.falling:
            self.vy += 1.4 * k
            y, floor = self.y + self.vy * k, self.floor_y()
            if y >= floor:
                y = floor
                if self.vy > 8:
                    self.vy = -self.vy * 0.35
                    self.sound(PETS[self.s['pet']]['tap'], 0)
                else:
                    self.falling = False
                    self.save_pos()
            self.move(self.x, y)

        # 소리 미리 만들기 (한 번에 하나씩)
        if self.warm:
            kind, note = self.warm.pop(0)
            vol = VOLUMES[self.s['volume']]
            if vol:
                make_sound(kind, note, vol)

        if now > self.next_top:  # 다른 창에 가려지지 않게
            self.root.attributes('-topmost', True)
            self.next_top = now + 2
        if now > self.next_save:
            self.save()
            self.next_save = now + 30
        self.root.after(15, self.tick)


if __name__ == '__main__':
    Pet().root.mainloop()
