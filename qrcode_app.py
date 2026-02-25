import tkinter as tk
from tkinter import messagebox, filedialog
import qrcode
from qrcode.constants import ERROR_CORRECT_L, ERROR_CORRECT_M, ERROR_CORRECT_Q, ERROR_CORRECT_H
from PIL import Image, ImageTk
import threading
import time
import re

class QRCodeGenerator:
    def __init__(self, root):
        self.root = root
        self.root.title("二维码生成器")
        self.root.geometry("420x700")
        self.root.resizable(False, False)
        self.root.configure(bg="#f5f5f5")

        # 核心配置
        self.error_correction_map = {
            "L": ERROR_CORRECT_L,
            "M": ERROR_CORRECT_M,
            "Q": ERROR_CORRECT_Q,
            "H": ERROR_CORRECT_H
        }
        self.selected_error_level = tk.StringVar(value="M")
        self.tk_img = None  # 防止图片被垃圾回收
        self.qr_pil_image = None  # 保存PIL图片对象
        self.refresh_lock = threading.Lock()  # 防止重复刷新
        self.last_refresh_time = 0  # 防抖：避免输入过快频繁刷新
        self.qr_content = ""  # 保存最终生成二维码的内容（用于扫码跳转）

        # ========== UI 布局 ==========
        # 标题
        title_label = tk.Label(
            root, text="二维码生成器",
            font=("Microsoft YaHei", 20, "bold"),
            bg="#f5f5f5", fg="#222222"
        )
        title_label.pack(pady=20)

        # 二维码显示画布
        self.qr_frame = tk.Frame(root, bg="#f0f2f5", bd=1, relief="solid")
        self.qr_frame.pack(padx=20, pady=10, fill="both", expand=True)
        self.qr_canvas = tk.Canvas(self.qr_frame, bg="#f0f2f5", bd=0, highlightthickness=0)
        self.qr_canvas.pack(fill="both", expand=True, padx=20, pady=20)
        # 占位文字（提示扫码跳转）
        self.placeholder_id = self.qr_canvas.create_text(
            self.qr_canvas.winfo_width()/2, self.qr_canvas.winfo_height()/2,
            text="输入内容生成二维码\n（网址扫码自动跳转）", font=("Microsoft YaHei", 12),
            fill="#999999", tag="placeholder"
        )
        # 画布大小变化时更新占位/图片
        self.qr_canvas.bind("<Configure>", self.on_canvas_resize)

        # 输入框（绑定实时输入事件）
        input_label = tk.Label(
            root, text="请输入网址或文本内容",
            font=("Microsoft YaHei", 14),
            bg="#f5f5f5", fg="#666666"
        )
        input_label.pack(pady=(20, 5), anchor="w", padx=20)
        self.input_entry = tk.Entry(
            root, font=("Microsoft YaHei", 14),
            bd=0, relief="flat", highlightthickness=1,
            highlightbackground="#e0e0e0", highlightcolor="#4285f4"
        )
        self.input_entry.pack(padx=20, pady=5, fill="x", ipady=8)
        # 绑定实时输入事件
        self.input_entry.bind("<KeyRelease>", self.on_input_real_time)

        # 容错等级选择
        error_level_label = tk.Label(
            root, text="容错等级",
            font=("Microsoft YaHei", 14, "bold"),
            bg="#f5f5f5", fg="#222222"
        )
        error_level_label.pack(pady=(20, 10), anchor="w", padx=20)
        self.error_level_frame = tk.Frame(root, bg="#f5f5f5")
        self.error_level_frame.pack(padx=20, pady=5, fill="x")
        level_info = [("L", "7%"), ("M", "15%"), ("Q", "25%"), ("H", "30%")]
        self.error_buttons = {}
        for level, percentage in level_info:
            btn = tk.Button(
                self.error_level_frame, text=f"{level}\n{percentage}",
                font=("Microsoft YaHei", 14, "bold"),
                bg="#ffffff" if level != "M" else "#e8f0fe",
                fg="#222222" if level != "M" else "#1967d2",
                bd=1, relief="solid",
                command=lambda l=level: self.on_error_level_change(l)
            )
            btn.pack(side="left", expand=True, fill="both", padx=5)
            self.error_buttons[level] = btn

        # 功能按钮
        btn_frame = tk.Frame(root, bg="#f5f5f5")
        btn_frame.pack(padx=20, pady=20, fill="x")
        self.clear_button = tk.Button(
            btn_frame, text="清除内容", font=("Microsoft YaHei", 14),
            bg="#e0e0e0", fg="#999999", bd=0, relief="flat", state="disabled",
            command=self.clear_content
        )
        self.clear_button.pack(side="left", expand=True, fill="both", padx=(0,5), ipady=10)
        self.save_button = tk.Button(
            btn_frame, text="保存二维码", font=("Microsoft YaHei", 14),
            bg="#4285f4", fg="white", bd=0, relief="flat", state="disabled",
            command=self.save_qr_code
        )
        self.save_button.pack(side="right", expand=True, fill="both", padx=(5,0), ipady=10)

        # 底部信息
        contact_frame = tk.Frame(root, bg="#f5f5f5")
        contact_frame.pack(pady=4)
        contact_btn = tk.Button(
            contact_frame, text="✉️ 联系开发者",
            font=("Microsoft YaHei", 11),
            bg="#f5f5f5", fg="#444444", bd=0, relief="flat",
            activebackground="#e8f0fe",
            command=self.show_contact
        )
        contact_btn.pack()
        copyright_label = tk.Label(
            root, text="© 2026 蕭遞\n本作品采用 CC BY-NC-ND 4.0 国际许可协议授权",
            font=("Microsoft YaHei", 10),
            bg="#f5f5f5", fg="#666666"
        )
        copyright_label.pack(pady=6)

    # ========== 核心功能：网址补全 + 实时生成 ==========
    def complete_url(self, text):
        """智能补全网址前缀，确保扫码能跳转"""
        if not text:
            return text
        
        # 匹配常见网址格式（省略http/https/www的情况）
        url_pattern = re.compile(
            r'^(?:(?:https?://)?(?:www\.)?)?'  # 可选的前缀
            r'(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}'  # 域名（如baidu.com）
            r'(?:/\S*)?$',  # 可选路径
            re.IGNORECASE
        )
        
        # 匹配IP地址（如192.168.1.1:8080）
        ip_pattern = re.compile(
            r'^(?:(?:https?://)?)?'
            r'\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}'
            r'(?::\d+)?(?:/\S*)?$',
            re.IGNORECASE
        )

        # 如果是网址但缺少前缀，自动补全http://
        if url_pattern.match(text) or ip_pattern.match(text):
            if not text.startswith(('http://', 'https://')):
                return f"http://{text}"
        # 非网址则返回原内容
        return text

    def on_input_real_time(self, event):
        """输入内容实时刷新（加防抖）"""
        current_time = time.time()
        if current_time - self.last_refresh_time < 0.1:
            return
        self.last_refresh_time = current_time
        
        content = self.input_entry.get().strip()
        if content:
            self.clear_button.config(state="normal", bg="#f0f0f0", fg="#333")
            # 补全网址（核心：确保扫码能跳转）
            self.qr_content = self.complete_url(content)
            # 异步生成二维码
            threading.Thread(target=self.generate_qr_code, args=(self.qr_content,), daemon=True).start()
        else:
            self.clear_button.config(state="disabled", bg="#e0e0e0", fg="#999")
            self.save_button.config(state="disabled")
            self.clear_qr_display()
            self.qr_content = ""

    def on_error_level_change(self, level):
        """切换容错等级立即刷新二维码"""
        self.selected_error_level.set(level)
        # 更新按钮样式
        for l, btn in self.error_buttons.items():
            if l == level:
                btn.config(bg="#e8f0fe", fg="#1967d2")
            else:
                btn.config(bg="#ffffff", fg="#222222")
        # 立即刷新二维码
        if self.qr_content:
            threading.Thread(target=self.generate_qr_code, args=(self.qr_content,), daemon=True).start()

    def generate_qr_code(self, content):
        """生成二维码（用补全后的网址，确保扫码跳转）"""
        with self.refresh_lock:
            try:
                error_level = self.error_correction_map[self.selected_error_level.get()]
                # 生成二维码（参数优化，保证扫码识别率）
                qr = qrcode.QRCode(
                    version=None, error_correction=error_level,
                    box_size=10, border=4,  # 增大border提升扫码识别率
                    image_factory=None, mask_pattern=None
                )
                qr.add_data(content)  # 用补全后的完整网址生成
                qr.make(fit=True)
                self.qr_pil_image = qr.make_image(fill_color="black", back_color="white")
                # 主线程更新UI
                self.root.after(0, self.render_qr_image)
                self.root.after(0, lambda: self.save_button.config(state="normal"))
            except Exception as e:
                self.root.after(0, lambda: messagebox.showerror("错误", f"二维码生成失败：{str(e)}"))

    def render_qr_image(self):
        """渲染二维码到画布"""
        if not self.qr_pil_image:
            return
        cw = self.qr_canvas.winfo_width()
        ch = self.qr_canvas.winfo_height()
        if cw < 50 or ch < 50:
            return
        
        # 等比例缩放（保证清晰度）
        img_w, img_h = self.qr_pil_image.size
        scale = min((cw - 20)/img_w, (ch - 20)/img_h)
        new_w = int(img_w * scale)
        new_h = int(img_h * scale)
        img_resized = self.qr_pil_image.resize((new_w, new_h), Image.Resampling.LANCZOS)
        
        self.tk_img = ImageTk.PhotoImage(img_resized)
        self.qr_canvas.delete("qr_img")
        x = (cw - new_w) / 2
        y = (ch - new_h) / 2
        self.qr_canvas.create_image(x, y, anchor="nw", image=self.tk_img, tag="qr_img")
        self.qr_canvas.itemconfig("placeholder", state="hidden")

    # ========== 辅助功能 ==========
    def on_canvas_resize(self, event):
        """画布大小变化时更新占位/图片"""
        self.qr_canvas.coords("placeholder", event.width/2, event.height/2)
        if self.qr_pil_image:
            self.render_qr_image()

    def clear_qr_display(self):
        """清除二维码，显示占位文字"""
        self.qr_canvas.delete("qr_img")
        self.qr_canvas.itemconfig("placeholder", state="normal")
        self.qr_pil_image = None
        self.tk_img = None

    def clear_content(self):
        """清除输入内容"""
        self.input_entry.delete(0, tk.END)
        self.clear_qr_display()
        self.clear_button.config(state="disabled", bg="#e0e0e0", fg="#999")
        self.save_button.config(state="disabled")
        self.qr_content = ""

    def save_qr_code(self):
        """保存二维码"""
        if not self.qr_pil_image:
            messagebox.showwarning("提示", "请先生成二维码")
            return
        path = filedialog.asksaveasfilename(
            defaultextension=".png",
            filetypes=[("PNG图片", "*.png"), ("JPG图片", "*.jpg"), ("BMP图片", "*.bmp")]
        )
        if path:
            self.qr_pil_image.save(path)
            messagebox.showinfo("保存成功", "二维码已保存到指定路径！")

    def show_contact(self):
        """显示联系信息"""
        messagebox.showinfo("联系开发者", "开发者 QQ：1740443398\n商用授权请联系！")

if __name__ == "__main__":
    root = tk.Tk()
    app = QRCodeGenerator(root)
    root.mainloop()