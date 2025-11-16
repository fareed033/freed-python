import sys
import asyncio
import json
import sqlite3
import os
from datetime import datetime
from PySide6.QtWidgets import *
from PySide6.QtCore import *
from PySide6.QtGui import *
import winsound
import logging
import time
from qasync import QEventLoop, asyncSlot
from datetime import timedelta
from math import isnan, sqrt, exp, log  # إضافة log لـ d1
import pyqtgraph as pg
from pyqtgraph.exporters import ImageExporter
from scipy import stats  # إضافة لـ Z-scores
from scipy.stats import norm  # إضافة لـ N'(d1) في تقدير Vega
from functools import lru_cache  # إضافة للـ caching
import hashlib  # إضافة للهاش

try:
    from ib_async import *
except ImportError as e:
    print(f"خطأ في استيراد ib_async: {e}")
    sys.exit(1)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('trading_app.log'),
        logging.StreamHandler(sys.stdout)
    ]
)

ib = IB()
is_ib_connected = False

# متغيرات البيانات
N_STRIKES = 30
strikes = [0.0] * N_STRIKES
call_ints = [0] * N_STRIKES
put_ints = [0] * N_STRIKES
call_volumes = [0] * N_STRIKES
put_volumes = [0] * N_STRIKES
call_gammas = [0.0] * N_STRIKES
put_gammas = [0.0] * N_STRIKES
call_deltas = [0.0] * N_STRIKES
put_deltas = [0.0] * N_STRIKES
call_premiums = [0.0] * N_STRIKES
put_premiums = [0.0] * N_STRIKES
call_ivs = [0.0] * N_STRIKES
put_ivs = [0.0] * N_STRIKES
call_bid_ivs = [0.0] * N_STRIKES
call_ask_ivs = [0.0] * N_STRIKES
put_bid_ivs = [0.0] * N_STRIKES
put_ask_ivs = [0.0] * N_STRIKES
call_thetas = [0.0] * N_STRIKES
put_thetas = [0.0] * N_STRIKES
call_vegas = [0.0] * N_STRIKES
put_vegas = [0.0] * N_STRIKES
call_vol_at_bid = [0] * N_STRIKES
call_vol_at_ask = [0] * N_STRIKES
put_vol_at_bid = [0] * N_STRIKES
put_vol_at_ask = [0] * N_STRIKES
slp_values = [0.0] * N_STRIKES  # إضافة لـ SLP_t
current_price = 0.0
last_request_time = 0
sound_enabled = True
call_color = "#6495ED"
put_color = "#DC143C"
current_theme = "Dark"
selected_exchange = "CBOE"
pcr_history = []
expiration_date = None
r_rate = 0.05
q_yield = 0.0117
data_type = "Live"
weights = [1.0, 0.7, 1.0, 1.0, 1.0, 1.0]  # أوزان SLP_t: w1(-GEX), w2(ΔVol), w3(VolImb), w4(IVSkew), w5(VannaAlign), w6(RVratio)
vol_history = [[0, 0, 0] for _ in range(N_STRIKES)]  # تاريخ Volume لآخر 3 تحديثات لكل strike

# مسار سطح المكتب
# desktop_path = os.path.join(os.path.expanduser("~"), "Desktop")  # السطر الأصلي المعلّق
db_path = os.path.join(os.getcwd(), "spx_data.db")

# إنشاء قاعدة البيانات
def init_database():
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS ورقة1 (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            CALL_LAST REAL,
            CALL_VOLUME INTEGER,
            CALL_IMPL_BID_VOL REAL,
            CALL_IMPL_VOL REAL,
            CALL_IMPL_ASK_VOL REAL,
            CALL_OPEN_I INTEGER,
            CALL_DELTA REAL,
            CALL_GAMMA REAL,
            TIME TEXT,
            SPX_PRICE REAL,
            STRIKE REAL,
            DATA TEXT,
            PUT_LAST REAL,
            PUT_VOLUME INTEGER,
            PUT_IMPL_BID_VOL REAL,
            PUT_IMPL_VOL REAL,
            PUT_IMPL_ASK_VOL REAL,
            PUT_OPEN_I INTEGER,
            PUT_DELTA REAL,
            PUT_GAMMA REAL,
            GEX REAL,
            DWOI REAL,
            VOLUME_PCR REAL,
            OI_PCR REAL,
            FLOW REAL,
            VEGA REAL,
            VANNA REAL,
            CHARM REAL,
            THETA_DE REAL,
            GNI REAL,
            GAMMA_LEVELS REAL,
            EM_RANGE TEXT,
            GEP REAL,
            PRO_FLOW REAL,
            IV_SKEW REAL,
            FLIP_LEVEL REAL,
            VWGF REAL,
            SAGE REAL,
            GFPI REAL,
            VAGPFI REAL,
            SLP_T REAL,  -- إضافة عمود SLP_t
            نسبة_الاتجاهي REAL,
            نسبة_المخاطر REAL
        )
    ''')
    conn.commit()
    conn.close()
    print(f"تم إنشاء القاعدة في: {db_path}")

# حفظ البيانات
def save_to_database(row_data):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO ورقة1 (
            timestamp, CALL_LAST, CALL_VOLUME, CALL_IMPL_BID_VOL, CALL_IMPL_VOL, CALL_IMPL_ASK_VOL,
            CALL_OPEN_I, CALL_DELTA, CALL_GAMMA, TIME, SPX_PRICE, STRIKE, DATA,
            PUT_LAST, PUT_VOLUME, PUT_IMPL_BID_VOL, PUT_IMPL_VOL, PUT_IMPL_ASK_VOL,
            PUT_OPEN_I, PUT_DELTA, PUT_GAMMA, GEX, DWOI, VOLUME_PCR, OI_PCR, FLOW,
            VEGA, VANNA, CHARM, THETA_DE, GNI, GAMMA_LEVELS, EM_RANGE, GEP, PRO_FLOW,
            IV_SKEW, FLIP_LEVEL, VWGF, SAGE, GFPI, VAGPFI, SLP_T, نسبة_الاتجاهي, نسبة_المخاطر
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', row_data)
    conn.commit()
    conn.close()

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("الإعدادات")
        self.setFixedSize(400, 300)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        self.setStyleSheet(""" 
            QDialog { background-color: %s; }
            QLabel { color: %s; font-size: 14px; }
            QComboBox, QCheckBox { color: %s; }
            QPushButton { 
                background-color: %s; 
                color: %s; 
                border: 1px solid %s; 
                padding: 5px; 
                border-radius: 3px; 
            }
            QPushButton:hover { background-color: %s; }
        """ % (
            "#2b2b2b" if current_theme == "Dark" else "#F5F5F5",
            "#FFFFFF" if current_theme == "Dark" else "#000000",
            "#FFFFFF" if current_theme == "Dark" else "#000000",
            "#4a4a4a" if current_theme == "Dark" else "#D3D3D3",
            "#FFFFFF" if current_theme == "Dark" else "#000000",
            "#555555" if current_theme == "Dark" else "#A9A9A9",
            "#5a5a5a" if current_theme == "Dark" else "#C0C0C0"
        ))

        theme_label = QLabel("الثيم:")
        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark Mode", "Light Mode"])
        self.theme_combo.setCurrentText("Dark Mode" if current_theme == "Dark" else "Light Mode")
        layout.addWidget(theme_label)
        layout.addWidget(self.theme_combo)

        update_label = QLabel("تردد التحديث:")
        self.update_combo = QComboBox()
        self.update_combo.addItems(["30 ثانية", "60 ثانية", "120 ثانية", "إيقاف"])
        self.update_combo.setCurrentText("60 ثانية")
        layout.addWidget(update_label)
        layout.addWidget(self.update_combo)

        self.sound_checkbox = QCheckBox("تفعيل صوت التنبيه")
        self.sound_checkbox.setChecked(sound_enabled)
        layout.addWidget(self.sound_checkbox)

        colors_layout = QHBoxLayout()
        call_color_btn = QPushButton("اختر لون Call")
        call_color_btn.clicked.connect(self.choose_call_color)
        put_color_btn = QPushButton("اختر لون Put")
        put_color_btn.clicked.connect(self.choose_put_color)
        colors_layout.addWidget(call_color_btn)
        colors_layout.addWidget(put_color_btn)
        layout.addLayout(colors_layout)

        buttons = QDialogButtonBox(QDialogButtonBox.Apply | QDialogButtonBox.Close)
        buttons.accepted.connect(self.apply_settings)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        self.setLayout(layout)

    def choose_call_color(self):
        global call_color
        color = QColorDialog.getColor(QColor(call_color), self)
        if color.isValid():
            call_color = color.name()

    def choose_put_color(self):
        global put_color
        color = QColorDialog.getColor(QColor(put_color), self)
        if color.isValid():
            put_color = color.name()

    def apply_settings(self):
        global current_theme, sound_enabled
        current_theme = "Dark" if self.theme_combo.currentText() == "Dark Mode" else "Light"
        update_interval = {
            "30 ثانية": 30000,
            "60 ثانية": 60000,
            "120 ثانية": 120000,
            "إيقاف": 0
        }[self.update_combo.currentText()]
        if update_interval > 0:
            self.parent().timer.setInterval(update_interval)
            self.parent().timer.start()
        else:
            self.parent().timer.stop()
        sound_enabled = self.sound_checkbox.isChecked()
        self.parent().update_theme()
        self.accept()


class ManualInputDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("إدخال يدوي")
        self.setFixedSize(1400, 800)
        self.parent = parent
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        self.inputs = []
        for i in range(N_STRIKES):
            strike_box = QGroupBox(f"Strike {i+1}")
            strike_layout = QGridLayout(strike_box)
            labels = ["Strike Price", "Call INT", "Put INT", "Call Volume", "Put Volume", 
                      "Call Gamma", "Put Gamma", "Call Delta", "Put Delta",
                      "Call Vol@Bid", "Call Vol@Ask", "Put Vol@Bid", "Put Vol@Ask"]
            inputs = []
            for j, label in enumerate(labels):
                strike_layout.addWidget(QLabel(label), j, 0)
                input_field = QLineEdit()
                if label in ["Call INT", "Call Volume", "Call Gamma", "Call Delta", "Call Vol@Bid", "Call Vol@Ask"]:
                    input_field.setStyleSheet(f"color: {call_color}; background-color: #FFFFFF; border: 1px solid #555555; padding: 3px;")
                elif label in ["Put INT", "Put Volume", "Put Gamma", "Put Delta", "Put Vol@Bid", "Put Vol@Ask"]:
                    input_field.setStyleSheet(f"color: {put_color}; background-color: #FFFFFF; border: 1px solid #555555; padding: 3px;")
                else:
                    input_field.setStyleSheet("color: #000000; background-color: #FFFFFF; border: 1px solid #555555; padding: 3px;")
                strike_layout.addWidget(input_field, j, 1)
                inputs.append(input_field)
            manual_btn = QPushButton("إدخال يدوي")
            manual_btn.clicked.connect(lambda _, idx=i: self.parent.use_manual_data(idx, self.inputs))
            strike_layout.addWidget(manual_btn, len(labels), 0, 1, 2)
            self.inputs.append(inputs)
            layout.addWidget(strike_box)
        self.setLayout(layout)


class GraphsDialog(QDialog):
    def __init__(self, parent=None, data=[], net_flow_values=[], pro_flow_values=[], pcr_history=[], slp_values=[]):
        super().__init__(parent)
        self.setWindowTitle("الرسوم البيانية")
        self.setMinimumSize(800, 600)
        self.data = data
        self.net_flow_values = net_flow_values
        self.pro_flow_values = pro_flow_values
        self.pcr_history = pcr_history
        self.slp_values = slp_values  # إضافة لـ SLP_t
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()
        tab_widget = QTabWidget()
        layout.addWidget(tab_widget)

        direction_widget = QWidget()
        direction_layout = QVBoxLayout(direction_widget)
        self.direction_plot = pg.PlotWidget()
        self.direction_plot.showGrid(x=True, y=True)
        self.direction_plot.setLabel('bottom', 'Equations')
        self.direction_plot.setLabel('left', 'Value')
        direction_layout.addWidget(self.direction_plot)
        tab_widget.addTab(direction_widget, "Equation Directions")

        gamma_widget = QWidget()
        gamma_layout = QVBoxLayout(gamma_widget)
        self.gamma_plot = pg.PlotWidget()
        self.gamma_plot.showGrid(x=True, y=True)
        self.gamma_plot.setLabel('bottom', 'Strikes')
        self.gamma_plot.setLabel('left', 'Gamma Levels')
        gamma_layout.addWidget(self.gamma_plot)
        tab_widget.addTab(gamma_widget, "Gamma Distribution")

        pcr_widget = QWidget()
        pcr_layout = QVBoxLayout(pcr_widget)
        self.pcr_plot = pg.PlotWidget()
        self.pcr_plot.showGrid(x=True, y=True)
        self.pcr_plot.setLabel('bottom', 'Updates')
        self.pcr_plot.setLabel('left', 'PCR Value')
        pcr_layout.addWidget(self.pcr_plot)
        tab_widget.addTab(pcr_widget, "PCR Evolution")

        flow_widget = QWidget()
        flow_layout = QVBoxLayout(flow_widget)
        self.flow_plot = pg.PlotWidget()
        self.flow_plot.showGrid(x=True, y=True)
        self.flow_plot.setLabel('bottom', 'Strikes')
        self.flow_plot.setLabel('left', 'Pro Net Flow ($)')
        flow_layout.addWidget(self.flow_plot)
        tab_widget.addTab(flow_widget, "Pro Net Flow")

        # إضافة تبويب لـ SLP_t
        slp_widget = QWidget()
        slp_layout = QVBoxLayout(slp_widget)
        self.slp_plot = pg.PlotWidget()
        self.slp_plot.showGrid(x=True, y=True)
        self.slp_plot.setLabel('bottom', 'Strikes')
        self.slp_plot.setLabel('left', 'SLP_t Value')
        slp_layout.addWidget(self.slp_plot)
        tab_widget.addTab(slp_widget, "SLP_t Pressure")

        filter_layout = QHBoxLayout()
        filter_label = QLabel("فلتر:")
        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["الكل", "Bullish فقط", "Bearish فقط"])
        self.filter_combo.currentTextChanged.connect(self.update_graphs)
        filter_layout.addWidget(filter_label)
        filter_layout.addWidget(self.filter_combo)
        layout.addLayout(filter_layout)

        export_btn = QPushButton("تصدير الرسم")
        export_btn.clicked.connect(self.export_graph)
        layout.addWidget(export_btn)

        self.setLayout(layout)
        self.update_graphs()

    def update_graphs(self, filter_text="الكل"):
        filtered_data = self.data
        if filter_text == "Bullish فقط":
            filtered_data = [d for d in self.data if d.get("Direction") == "Call"]
        elif filter_text == "Bearish فقط":
            filtered_data = [d for d in self.data if d.get("Direction") == "Put"]

        self.direction_plot.clear()
        equations = ['GEX', 'DWOI', 'Volume PCR', 'OI PCR', 'FLOW', 'PRO FLOW', 'VEGA', 'VANNA', 'Charm', 'Theta Decay', 'GNI', 'IV SKEW', 'TAIL RISK', 'VWGF', 'SAGE', 'GFPI', 'VAGPFI']
        x = list(range(len(equations)))
        values = []
        for key in equations:
            val_sum = 0
            count = 0
            for d in filtered_data:
                val = d.get(key, 0)
                if isinstance(val, (int, float)):
                    val_sum += val
                    count += 1
            val_avg = val_sum / count if count > 0 else 0
            values.append(val_avg)
        brushes = ['g' if v > 0 else 'r' if v < 0 else 'y' for v in values]
        bars = pg.BarGraphItem(x=x, height=values, width=0.6, brushes=brushes)
        self.direction_plot.addItem(bars)
        self.direction_plot.addLine(y=0, pen='w')

        self.gamma_plot.clear()
        gamma_x = list(range(len(filtered_data)))
        gamma_levels = [d.get("GAMMA LEVELS", 0) for d in filtered_data]
        gamma_bar = pg.BarGraphItem(x=gamma_x, height=gamma_levels, width=0.3, brushes=['b' if h > 0 else 'r' for h in gamma_levels])
        self.gamma_plot.addItem(gamma_bar)

        self.pcr_plot.clear()
        if self.pcr_history:
            volumes = [h[0] for h in self.pcr_history if h[0] != "N/A"]
            ois = [h[1] for h in self.pcr_history if h[1] != "N/A"]
            self.pcr_plot.plot(range(len(volumes)), volumes, pen='b', name="Volume PCR")
            self.pcr_plot.plot(range(len(ois)), ois, pen='r', name="OI PCR")

        self.flow_plot.clear()
        strikes_sorted = sorted(filtered_data, key=lambda x: x["Strike"])
        x_flow = [d["Strike"] for d in strikes_sorted]
        y_flow = [d.get("PRO FLOW", 0) for d in strikes_sorted]
        self.flow_plot.plot(x_flow, y_flow, pen='y', symbol='o', symbolBrush='c', name="Pro Net Flow")

        # رسم SLP_t
        self.slp_plot.clear()
        slp_x = list(range(len(self.slp_values)))
        slp_y = self.slp_values
        brushes_slp = ['g' if v > 0 else 'r' for v in slp_y]
        slp_bar = pg.BarGraphItem(x=slp_x, height=slp_y, width=0.6, brushes=brushes_slp)
        self.slp_plot.addItem(slp_bar)
        self.slp_plot.addLine(y=0, pen='w')

    def export_graph(self):
        exporter = ImageExporter(self.direction_plot.plotItem)
        exporter.export('direction_graph.png')
        exporter = ImageExporter(self.gamma_plot.plotItem)
        exporter.export('gamma_graph.png')
        exporter = ImageExporter(self.pcr_plot.plotItem)
        exporter.export('pcr_graph.png')
        exporter = ImageExporter(self.flow_plot.plotItem)
        exporter.export('pro_flow_graph.png')
        exporter = ImageExporter(self.slp_plot.plotItem)  # إضافة تصدير SLP
        exporter.export('slp_graph.png')
        self.parent().status_bar.showMessage("تم تصدير الرسوم بنجاح")


class CustomDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        super().paint(painter, option, index)
        if index.row() == 15:  # تعديل للصف الأوسط (15 من 30)
            pen = QPen(QColor("#87CEFA"), 2, Qt.SolidLine)
            painter.setPen(pen)
            painter.drawLine(option.rect.bottomLeft(), option.rect.bottomRight())


class SPXTradingApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FOFONACCI")
        self.setGeometry(100, 100, 1600, 800)
        self.strike_recommendations = []
        self.data = []
        self.net_flow_values = []
        self.pro_flow_values = []
        self.update_interval = 10000  # 10 ثوانٍ
        self.last_data_hash = {}  # لتخزين هاش البيانات السابقة
        self.init_ui()
        init_database()
        self.db_timer = QTimer()
        self.db_timer.timeout.connect(self.save_all_data)
        self.db_timer.start(60000)

    def save_all_data(self):
        if not hasattr(self, 'last_save_time'):
            self.last_save_time = 0
        current_time = time.time()
        if current_time - self.last_save_time < 60:  # حفظ كل 60 ثانية فقط
            return
        self.last_save_time = current_time
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for i in range(N_STRIKES):  # استخدم i للوصول إلى المتغيرات العالمية
            if strikes[i] <= 0:  # تجاهل الستريكات الفارغة
                continue
            row_data = (
                timestamp,
                call_premiums[i],  # CALL_LAST من المتغير العالمي
                call_volumes[i],   # CALL_VOLUME
                call_bid_ivs[i],   # CALL_IMPL_BID_VOL
                call_ivs[i],       # CALL_IMPL_VOL
                call_ask_ivs[i],   # CALL_IMPL_ASK_VOL
                call_ints[i],      # CALL_OPEN_I
                call_deltas[i],    # CALL_DELTA
                call_gammas[i],    # CALL_GAMMA
                datetime.now().strftime("%H:%M:%S"),  # TIME
                current_price,     # SPX_PRICE
                strikes[i],        # STRIKE
                "Auto",            # DATA
                put_premiums[i],   # PUT_LAST
                put_volumes[i],    # PUT_VOLUME
                put_bid_ivs[i],    # PUT_IMPL_BID_VOL
                put_ivs[i],        # PUT_IMPL_VOL
                put_ask_ivs[i],    # PUT_IMPL_ASK_VOL
                put_ints[i],       # PUT_OPEN_I
                put_deltas[i],     # PUT_DELTA
                put_gammas[i],     # PUT_GAMMA
                self.data[i].get("GEX", 0) if i < len(self.data) else 0,  # GEX من self.data
                self.data[i].get("DWOI", 0) if i < len(self.data) else 0, # DWOI
                self.data[i].get("Volume PCR", 0) if i < len(self.data) else 0,  # VOLUME_PCR
                self.data[i].get("OI PCR", 0) if i < len(self.data) else 0,       # OI_PCR
                self.data[i].get("FLOW", 0) if i < len(self.data) else 0,         # FLOW
                self.data[i].get("VEGA", 0) if i < len(self.data) else 0,         # VEGA
                self.data[i].get("VANNA", 0) if i < len(self.data) else 0,        # VANNA
                self.data[i].get("Charm", 0) if i < len(self.data) else 0,        # CHARM
                self.data[i].get("Theta Decay", 0) if i < len(self.data) else 0,  # THETA_DE
                self.data[i].get("GNI", 0) if i < len(self.data) else 0,          # GNI
                self.data[i].get("GAMMA LEVELS", 0) if i < len(self.data) else 0, # GAMMA_LEVELS
                self.data[i].get("EM Range", "") if i < len(self.data) else "",   # EM_RANGE
                self.data[i].get("GEP", 0) if i < len(self.data) else 0,          # GEP
                self.data[i].get("PRO FLOW", 0) if i < len(self.data) else 0,     # PRO_FLOW
                self.data[i].get("IV SKEW", 0) if i < len(self.data) else 0,      # IV_SKEW
                self.data[i].get("FLIP LEVEL", 0) if i < len(self.data) else 0,   # FLIP_LEVEL
                self.data[i].get("VWGF", 0) if i < len(self.data) else 0,         # VWGF
                self.data[i].get("SAGE", 0) if i < len(self.data) else 0,         # SAGE
                self.data[i].get("GFPI", 0) if i < len(self.data) else 0,         # GFPI
                self.data[i].get("VAGPFI", 0) if i < len(self.data) else 0,       # VAGPFI
                self.data[i].get("SLP_T", 0) if i < len(self.data) else 0,        # SLP_T
                self.data[i].get("dir_percentage", 0) if i < len(self.data) else 0,  # نسبة_الاتجاهي
                self.data[i].get("risk_percentage", 0) if i < len(self.data) else 0  # نسبة_المخاطر
            )
            try:
                save_to_database(row_data)
            except Exception as e:
                logging.error(f"خطأ في حفظ السطر {i}: {e}")
        self.status_bar.showMessage(f"تم حفظ البيانات في القاعدة: {timestamp}")

    def init_ui(self):
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)

        self.dark_style = """
            QMainWindow, QWidget { background-color: #2b2b2b; }
            QLabel { color: #FFFFFF; font-size: 14px; }
            QPushButton { 
                background-color: #4a4a4a; 
                color: #FFFFFF; 
                border: 1px solid #555555; 
                padding: 5px; 
                border-radius: 3px; 
            }
            QPushButton:hover { background-color: #5a5a5a; }
            QLineEdit { 
                background-color: #FFFFFF; 
                color: #000000; 
                border: 1px solid #555555; 
                padding: 3px; 
            }
            QComboBox { 
                background-color: #4a4a4a; 
                color: #FFFFFF; 
                border: 1px solid #555555; 
                padding: 3px; 
                border-radius: 3px; 
            }
            QComboBox:hover { background-color: #5a5a5a; }
            QGroupBox { 
                color: #FFFFFF; 
                font-size: 14px; 
                font-weight: bold; 
                border: 1px solid #555555; 
                border-radius: 5px; 
                margin-top: 10px; 
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                subcontrol-position: top center; 
                padding: 0 3px; 
            }
            QTableWidget { 
                background-color: #2b2b2b; 
                color: #FFFFFF; 
                gridline-color: #555555; 
                selection-background-color: #777777; 
            }
            QTableWidget::item { padding: 5px; }
            QHeaderView::section { 
                background-color: #4a4a4a; 
                color: #FFFFFF; 
                padding: 5px; 
                border: 1px solid #555555; 
            }
        """
        self.light_style = """
            QMainWindow, QWidget { background-color: #F5F5F5; }
            QLabel { color: #000000; font-size: 14px; }
            QPushButton { 
                background-color: #D3D3D3; 
                color: #000000; 
                border: 1px solid #A9A9A9; 
                padding: 5px; 
                border-radius: 3px; 
            }
            QPushButton:hover { background-color: #C0C0C0; }
            QLineEdit { 
                background-color: #FFFFFF; 
                color: #000000; 
                border: 1px solid #A9A9A9; 
                padding: 3px; 
            }
            QComboBox { 
                background-color: #D3D3D3; 
                color: #000000; 
                border: 1px solid #A9A9A9; 
                padding: 3px; 
                border-radius: 3px; 
            }
            QComboBox:hover { background-color: #C0C0C0; }
            QGroupBox { 
                color: #000000; 
                font-size: 14px; 
                font-weight: bold; 
                border: 1px solid #A9A9A9; 
                border-radius: 5px; 
                margin-top: 10px; 
            }
            QGroupBox::title { 
                subcontrol-origin: margin; 
                subcontrol-position: top center; 
                padding: 0 3px; 
            }
            QTableWidget { 
                background-color: #F5F5F5; 
                color: #000000; 
                gridline-color: #A9A9A9; 
                selection-background-color: #C0C0C0; 
            }
            QTableWidget::item { padding: 5px; }
            QHeaderView::section { 
                background-color: #D3D3D3; 
                color: #000000; 
                padding: 5px; 
                border: 1px solid #A9A9A9; 
            }
        """
        self.setStyleSheet(self.dark_style)

        top_widget = QWidget()
        top_layout = QHBoxLayout(top_widget)

        manual_btn = QPushButton()
        manual_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogNewFolder))
        manual_btn.setFixedSize(24, 24)
        manual_btn.setToolTip("إدخال يدوي")
        manual_btn.clicked.connect(self.open_manual_dialog)
        top_layout.addWidget(manual_btn)

        settings_btn = QPushButton()
        settings_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogDetailedView))
        settings_btn.setFixedSize(24, 24)
        settings_btn.clicked.connect(self.open_settings)
        top_layout.addWidget(settings_btn)

        graphs_btn = QPushButton()
        graphs_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        graphs_btn.setFixedSize(24, 24)
        graphs_btn.setToolTip("الرسوم البيانية")
        graphs_btn.clicked.connect(self.open_graphs_dialog)
        top_layout.addWidget(graphs_btn)

        exchange_label = QLabel("Exchange:")
        exchange_label.setStyleSheet("color: #FFFFFF;" if current_theme == "Dark" else "color: #000000;")
        top_layout.addWidget(exchange_label)
        self.exchange_combo = QComboBox()
        self.exchange_combo.addItems(["CBOE", "SMART", "BOX"])
        self.exchange_combo.setCurrentText("CBOE")
        self.exchange_combo.currentTextChanged.connect(self.update_exchange)
        top_layout.addWidget(self.exchange_combo)

        self.title_label = QLabel("FOFONACCI")
        self.title_label.setFont(QFont("Arial", 16, QFont.Bold))
        top_layout.addWidget(self.title_label)
        top_layout.addStretch()

        spx_group = QGroupBox("سعر SPX")
        spx_layout = QHBoxLayout(spx_group)

        self.data_type_btn = QPushButton("Live" if data_type == "Live" else "Delayed")
        self.data_type_btn.setFixedSize(24, 24)
        self.data_type_btn.setToolTip("تبديل نوع البيانات")
        self.data_type_btn.setCursor(QCursor(Qt.PointingHandCursor))
        self.data_type_btn.clicked.connect(self.show_data_type_menu)
        spx_layout.addWidget(self.data_type_btn)

        self.spx_price_label = QLabel("سعر SPX الحالي: 0.0")
        spx_layout.addWidget(self.spx_price_label)
        update_price_btn = QPushButton("تحديث سعر SPX")
        update_price_btn.clicked.connect(self.fetch_spx_price)
        spx_layout.addWidget(update_price_btn)
        spx_layout.addWidget(QLabel("سعر يدوي:"))
        self.manual_price_input = QLineEdit()
        spx_layout.addWidget(self.manual_price_input)
        use_manual_btn = QPushButton("استخدام")
        use_manual_btn.clicked.connect(self.use_manual_price)
        spx_layout.addWidget(use_manual_btn)
        self.toggle_button = QPushButton("فصل الاتصال" if is_ib_connected else "اتصل بـ IB")
        self.toggle_button.clicked.connect(self.toggle_ib_connection)
        spx_layout.addWidget(self.toggle_button)
        update_table_btn = QPushButton("تحديث الجدول")
        update_table_btn.clicked.connect(self.analyze_data)
        spx_layout.addWidget(update_table_btn)
        fetch_options_btn = QPushButton("جلب الخيارات")
        fetch_options_btn.clicked.connect(self.fetch_options_data)
        spx_layout.addWidget(fetch_options_btn)
        spx_layout.addWidget(QLabel("r Rate:"))
        self.r_rate_input = QLineEdit(str(r_rate))
        spx_layout.addWidget(self.r_rate_input)
        spx_layout.addWidget(QLabel("q Yield:"))
        self.q_yield_input = QLineEdit(str(q_yield))
        spx_layout.addWidget(self.q_yield_input)
        use_params_btn = QPushButton("تأكيد")
        use_params_btn.clicked.connect(self.use_manual_params)
        spx_layout.addWidget(use_params_btn)
        top_layout.addWidget(spx_group)

        main_layout.addWidget(top_widget)

        splitter = QSplitter(Qt.Vertical)
        main_layout.addWidget(splitter)

        auto_group = QGroupBox("بيانات الخيارات التلقائية")
        auto_layout = QVBoxLayout(auto_group)
        self.auto_table = QTableWidget()
        self.auto_table.setRowCount(N_STRIKES)
        self.auto_table.setColumnCount(17)
        self.auto_table.setHorizontalHeaderLabels([
            "Call Last", "Call Volume", "Call Impl. Bid Vol.", "Call Impld Vol. %", "Call Impl. Ask Vol.", "Call Optn Opn I...", "Call Delta", "Call Gamma",
            "Strike",
            "Put Gamma", "Put Delta", "Put Optn Opn I...", "Put Impl. Ask Vol.", "Put Impld Vol. %", "Put Impl. Bid Vol.", "Put Volume", "Put Last"
        ])
        self.auto_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.auto_table.verticalHeader().setVisible(False)
        self.auto_table.setStyleSheet("QTableWidget::item { text-align: center; }")
        self.auto_table.setItemDelegate(CustomDelegate(self.auto_table))
        auto_scroll = QScrollArea()
        auto_scroll.setWidget(self.auto_table)
        auto_scroll.setWidgetResizable(True)
        auto_layout.addWidget(auto_scroll)
        splitter.addWidget(auto_group)

        self.tab_widget = QTabWidget()
        splitter.addWidget(self.tab_widget)

        # تبويب التوصيات النهائية
        recommendations_widget = QWidget()
        recommendations_layout = QVBoxLayout(recommendations_widget)
        results_group = QGroupBox("التوصيات النهائية")
        results_layout = QVBoxLayout(results_group)
        self.table = QTableWidget()
        self.table.setRowCount(N_STRIKES)
        self.table.setColumnCount(22)  # إضافة عمود SLP_t
        self.table.setHorizontalHeaderLabels([
            "Strike", "PRO FLOW", "FLOW", "Volume PCR", "DWOI", "GEX", "OI PCR",
            "TAIL RISK", "IV SKEW", "VEGA", "VANNA", "GNI", "Theta Decay", "Charm",
            "FLIP LEVEL", "GAMMA LEVELS", "EM Range", "VWGF", "SAGE", "GFPI", "VAGPFI", "SLP_t"
        ])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.verticalHeader().setVisible(True)
        table_scroll = QScrollArea()
        table_scroll.setWidget(self.table)
        table_scroll.setWidgetResizable(True)
        results_layout.addWidget(table_scroll)
        recommendations_layout.addWidget(results_group)
        self.tab_widget.addTab(recommendations_widget, "التوصيات النهائية")

        # تبويب توصيات المعادلات (مع تعديل عدد الأعمدة إلى 7)
        eq_recommendations_widget = QWidget()
        eq_recommendations_layout = QVBoxLayout(eq_recommendations_widget)
        eq_group = QGroupBox("توصيات المعادلات")
        eq_layout = QVBoxLayout(eq_group)
        self.eq_table = QTableWidget()
        self.eq_table.setRowCount(12)
        self.eq_table.setColumnCount(7)  # تعديل: CALL RECOM, قوة (نجوم), Strike, PUT RECOM, SLP_t, اتجاهي, مخاطر
        self.eq_table.setHorizontalHeaderLabels(["CALL RECOM", "قوة الإشارة", "Strike", "PUT RECOM", "SLP_t", "نسبة اتجاهي", "نسبة مخاطر"])
        self.eq_table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.eq_table.verticalHeader().setVisible(False)
        eq_scroll = QScrollArea()
        eq_scroll.setWidget(self.eq_table)
        eq_scroll.setWidgetResizable(True)
        eq_layout.addWidget(eq_scroll)
        eq_recommendations_layout.addWidget(eq_group)
        self.tab_widget.addTab(eq_recommendations_widget, "توصيات المعادلات")

        self.filter_combo = QComboBox()
        self.filter_combo.addItems(["الكل", "Bullish فقط", "Bearish فقط"])
        self.filter_combo.currentTextChanged.connect(self.apply_filter)
        main_layout.addWidget(self.filter_combo)

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.setStyleSheet("QStatusBar { color: white; }")
        self.status_bar.showMessage("جاهز")

        self.timer = QTimer()
        self.timer.timeout.connect(self.periodic_update)
        self.timer.start(self.update_interval)  # استخدام الـ interval الجديد

        self.load_params()

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 1)

        screen = QApplication.primaryScreen().geometry()
        self.resize(screen.width(), 800)
        self.setMinimumSize(1200, 600)
        self.setWindowFlags(Qt.Window | Qt.WindowMinimizeButtonHint | Qt.WindowMaximizeButtonHint | Qt.WindowCloseButtonHint)
        self.showMaximized()

    def load_params(self):
        global r_rate, q_yield, data_type
        try:
            with open('config.json', 'r') as f:
                config = json.load(f)
                r_rate = config.get('r_rate', 0.05)
                q_yield = config.get('q_yield', 0.0117)
                data_type = config.get('data_type', "Live")
                self.r_rate_input.setText(str(r_rate))
                self.q_yield_input.setText(str(q_yield))
                self.data_type_btn.setText("Live" if data_type == "Live" else "Delayed")
        except FileNotFoundError:
            pass

    def show_data_type_menu(self):
        menu = QMenu(self)
        live_action = menu.addAction("Live")
        delayed_action = menu.addAction("Delayed - 15 دقيقة")
        live_action.triggered.connect(lambda: self.set_data_type("Live"))
        delayed_action.triggered.connect(lambda: self.set_data_type("Delayed"))
        menu.exec(QCursor.pos())

    def set_data_type(self, new_type):
        global data_type
        data_type = new_type
        self.data_type_btn.setText("Live" if data_type == "Live" else "Delayed")
        self.save_params()
        self.status_bar.showMessage(f"تم تغيير نوع البيانات إلى {data_type}")
        logging.info(f"تم تغيير نوع البيانات إلى {data_type}")
        self.fetch_spx_price()

    def open_graphs_dialog(self):
        dialog = GraphsDialog(self, self.data, self.net_flow_values, self.pro_flow_values, pcr_history, slp_values)  # إضافة slp_values
        dialog.show()

    def open_manual_dialog(self):
        self.manual_dialog = ManualInputDialog(self)
        self.manual_dialog.exec_()

    def use_manual_data(self, index, inputs_list):
        try:
            inputs = inputs_list[index]
            strike = float(inputs[0].text()) if inputs[0].text() else 0.0
            call_int = int(inputs[1].text()) if inputs[1].text() else 0
            put_int = int(inputs[2].text()) if inputs[2].text() else 0
            call_volume = int(inputs[3].text()) if inputs[3].text() else 0
            put_volume = int(inputs[4].text()) if inputs[4].text() else 0
            call_gamma = float(inputs[5].text()) if inputs[5].text() else 0.0099
            put_gamma = float(inputs[6].text()) if inputs[6].text() else 0.0099
            call_delta = float(inputs[7].text()) if inputs[7].text() else 0.7427
            put_delta = float(inputs[8].text()) if inputs[8].text() else -0.2573
            call_vol_bid = int(inputs[9].text()) if inputs[9].text() else 0
            call_vol_ask = int(inputs[10].text()) if inputs[10].text() else 0
            put_vol_bid = int(inputs[11].text()) if inputs[11].text() else 0
            put_vol_ask = int(inputs[12].text()) if inputs[12].text() else 0

            if strike > 0 and call_int >= 0 and put_int >= 0 and call_volume >= 0 and put_volume >= 0:
                strikes[index] = strike
                call_ints[index] = call_int
                put_ints[index] = put_int
                call_volumes[index] = call_volume
                put_volumes[index] = put_volume
                call_gammas[index] = call_gamma
                put_gammas[index] = put_gamma
                call_deltas[index] = call_delta
                put_deltas[index] = put_delta
                call_vol_at_bid[index] = call_vol_bid
                call_vol_at_ask[index] = call_vol_ask
                put_vol_at_bid[index] = put_vol_bid
                put_vol_at_ask[index] = put_vol_ask

                self.update_auto_table()
                self.status_bar.showMessage(f"تم إدخال بيانات Strike {index+1} يدويًا")
                logging.info(f"تم إدخال بيانات Strike {index+1} يدويًا")
            else:
                self.status_bar.showMessage(f"تأكد من إدخال قيم صحيحة وغير سالبة لـStrike {index+1}")
                return

            self.analyze_data()
        except Exception as e:
            error_msg = f"أدخل بيانات يدوية صحيحة لـStrike {index+1}: {str(e)}"
            self.status_bar.showMessage(error_msg)
            logging.error(error_msg, exc_info=True)

    def apply_filter(self, filter_text):
        filter_type = "All"
        if filter_text == "Bullish فقط":
            filter_type = "Call"
        elif filter_text == "Bearish فقط":
            filter_type = "Put"
        self.analyze_data(filter_type)

    @asyncSlot()
    async def open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec_()

    def update_theme(self):
        global current_theme
        self.setStyleSheet(self.dark_style if current_theme == "Dark" else self.light_style)
        self.status_bar.setStyleSheet("QStatusBar { color: white; }")
        self.analyze_data()

    def update_exchange(self, exchange):
        global selected_exchange
        selected_exchange = exchange
        logging.info(f"تم تحديث Exchange إلى: {selected_exchange}")
        self.status_bar.showMessage(f"Exchange محدد: {selected_exchange}")

    @asyncSlot()
    async def toggle_ib_connection(self):
        global is_ib_connected
        try:
            if is_ib_connected:
                ib.disconnect()
                is_ib_connected = False
                self.toggle_button.setText("اتصل بـ IB")
                self.toggle_button.setStyleSheet("color: #FF4500;")
                self.title_label.setStyleSheet("color: #FF4500;")
                self.status_bar.showMessage("تم فصل الاتصال بـ Interactive Brokers")
                logging.info("تم فصل الاتصال بـ IB")
            else:
                port = 7496
                try:
                    await ib.connectAsync('127.0.0.1', port, clientId=1)
                    is_ib_connected = True
                    self.toggle_button.setText("فصل الاتصال")
                    self.toggle_button.setStyleSheet("color: #90EE90;")
                    self.title_label.setStyleSheet("color: #90EE90;")
                    self.status_bar.showMessage(f"تم الاتصال بـ Interactive Brokers على المنفذ {port}")
                    logging.info(f"تم الاتصال بـ IB على المنفذ {port}")
                except Exception as e:
                    logging.error(f"فشل الاتصال على المنفذ {port}: {str(e)}", exc_info=True)
                    self.status_bar.showMessage("فشل الاتصال بـIB Gateway/TWS. تحقق من الإعدادات.")
                    is_ib_connected = False
                    self.toggle_button.setStyleSheet("color: #FF4500;")
                    self.title_label.setStyleSheet("color: #FF4500;")
        except Exception as e:
            self.status_bar.showMessage(f"فشل تغيير حالة الاتصال: {str(e)}")
            logging.error(f"خطأ في تغيير حالة الاتصال: {str(e)}", exc_info=True)

    @asyncSlot()
    async def fetch_spx_price(self):
        if is_ib_connected:
            await self.fetch_spx_price_async()
        else:
            self.status_bar.showMessage("لا يوجد اتصال بـ IB")
            logging.info("لا يوجد اتصال بـ IB")

    async def fetch_spx_price_async(self):
        global last_request_time, current_price
        if not is_ib_connected:
            return

        current_time = time.time()
        if current_time - last_request_time < 11:
            return

        try:
            contract = Index('SPX', 'CBOE')
            await ib.qualifyContractsAsync(contract)
            ib.reqMarketDataType(1 if data_type == "Live" else 3)
            tickers = await ib.reqTickersAsync(contract)
            ticker = tickers[0]
            price = ticker.marketPrice() if data_type == "Live" else ticker.close

            if price and price > 0:
                current_price = round(price, 2)
                self.spx_price_label.setText(f"سعر SPX الحالي ({data_type}): {current_price}")
            else:
                raise ValueError("فشل جلب سعر SPX")

            last_request_time = current_time
            logging.info(f"تم جلب سعر SPX: {current_price}")
            self.status_bar.showMessage(f"تم جلب سعر SPX: {current_price}")
            self.analyze_data()
        except Exception as e:
            error_msg = f"فشل جلب سعر SPX: {str(e)}"
            self.status_bar.showMessage(f"{error_msg} استخدم الإدخال اليدوي")
            logging.error(error_msg, exc_info=True)
            current_price = 0.0
            self.spx_price_label.setText("سعر SPX الحالي: 0.0")

    def use_manual_price(self):
        global current_price
        try:
            spx_price = float(self.manual_price_input.text())
            if spx_price <= 0:
                self.status_bar.showMessage("السعر اليدوي يجب أن يكون أكبر من صفر")
                return
            current_price = spx_price
            self.spx_price_label.setText(f"سعر SPX الحالي (يدوي): {spx_price}")
            self.status_bar.showMessage(f"تم استخدام سعر SPX اليدوي: {spx_price}")
            logging.info(f"تم استخدام السعر اليدوي: {spx_price}")
            self.analyze_data()
        except Exception as e:
            error_msg = f"أدخل سعر SPX يدوي صحيح: {str(e)}"
            self.status_bar.showMessage(error_msg)
            logging.error(error_msg, exc_info=True)

    def use_manual_params(self):
        global r_rate, q_yield
        try:
            r_rate = float(self.r_rate_input.text())
            q_yield = float(self.q_yield_input.text())
            self.save_params()
            self.status_bar.showMessage("تم تحديث قيم r و q بنجاح")
            logging.info(f"تم تحديث r_rate إلى {r_rate} و q_yield إلى {q_yield}")
            self.analyze_data()
        except Exception as e:
            error_msg = f"أدخل قيم r و q صحيحة: {str(e)}"
            self.status_bar.showMessage(error_msg)
            logging.error(error_msg, exc_info=True)

    def save_params(self):
        config = {
            'r_rate': r_rate,
            'q_yield': q_yield,
            'data_type': data_type
        }
        with open('config.json', 'w') as f:
            json.dump(config, f)

    @asyncSlot()
    async def periodic_update(self):
        if is_ib_connected:
            # جلب كامل دفعة واحدة
            await self.fetch_spx_options_async()
            
            # التحقق من التغييرات عبر هاش
            current_hash = hash(str([strikes[:], call_ints[:], put_ints[:]]))
            if current_hash == self.last_data_hash.get('full', 0):
                return  # تجاهل إذا لم تتغير
            self.last_data_hash['full'] = current_hash
            
            self.analyze_data()
        else:
            self.status_bar.showMessage("لا يوجد اتصال بـ IB")

    @asyncSlot()
    async def fetch_options_data(self):
        if is_ib_connected:
            try:
                await self.fetch_spx_options_async()  # الجلب الكامل للزر اليدوي
                self.status_bar.showMessage("تم جلب بيانات الخيارات بنجاح")
                logging.info("تم جلب بيانات الخيارات بنجاح")
            except Exception as e:
                error_msg = f"فشل جلب بيانات الخيارات: {str(e)}"
                self.status_bar.showMessage(error_msg)
                logging.error(error_msg, exc_info=True)
        else:
            self.status_bar.showMessage("لا يوجد اتصال بـ IB")

    async def fetch_spx_options_async(self):
        global last_request_time, selected_exchange, expiration_date, strikes, call_ints, put_ints, call_volumes, put_volumes, call_gammas, put_gammas, call_deltas, put_deltas, call_premiums, put_premiums, call_ivs, put_ivs, call_bid_ivs, call_ask_ivs, put_bid_ivs, put_ask_ivs, call_thetas, put_thetas, call_vegas, put_vegas, call_vol_at_bid, call_vol_at_ask, put_vol_at_bid, put_vol_at_ask, slp_values, r_rate, q_yield
        if not is_ib_connected:
            return

        current_time = time.time()
        if current_time - last_request_time < 11:
            return

        try:
            ib.reqMarketDataType(1 if data_type == "Live" else 3)
            await self.fetch_spx_price_async()
            spx_price = current_price
            if spx_price == 0:
                raise ValueError("فشل جلب سعر SPX")

            contract = Index('SPX', 'CBOE')
            await ib.qualifyContractsAsync(contract)

            chains = await ib.reqSecDefOptParamsAsync(
                underlyingSymbol=contract.symbol,
                futFopExchange='',
                underlyingSecType=contract.secType,
                underlyingConId=contract.conId
            )
            if not chains:
                raise ValueError("لم يتم العثور على سلسلة خيارات.")

            chain = next((c for c in chains if c.exchange == 'CBOE'), None)
            if not chain:
                raise ValueError("لم يتم العثور على سلسلة خيارات لـ CBOE.")

            min_expiration = datetime.now().strftime('%Y%m%d')
            max_expiration = (datetime.now() + timedelta(days=30)).strftime('%Y%m%d')
            expiration = next((exp for exp in chain.expirations if min_expiration <= exp <= max_expiration), None)
            if not expiration and chain.expirations:
                expiration = chain.expirations[0]
            if not expiration:
                raise ValueError("لم يتم العثور على تاريخ انتهاء صلاحية صالح")
            expiration_date = datetime.strptime(expiration, '%Y%m%d')

            # حساب T للتقدير (يُستخدم في تقدير Vega)
            today = datetime.now()
            t_days = max((expiration_date - today).days, 1)
            T = t_days / 365.0

            above_strikes = sorted([s for s in chain.strikes if s > spx_price], key=lambda x: abs(x - spx_price))[:15]
            below_strikes = sorted([s for s in chain.strikes if s < spx_price], key=lambda x: abs(x - spx_price))[:15]
            temp_strikes_list = above_strikes + below_strikes

            contracts = []
            for strike in temp_strikes_list:
                call_contract = Option(symbol='SPX', lastTradeDateOrContractMonth=expiration, strike=strike, right='C', exchange=selected_exchange)
                put_contract = Option(symbol='SPX', lastTradeDateOrContractMonth=expiration, strike=strike, right='P', exchange=selected_exchange)
                contracts.extend([call_contract, put_contract])

            qualified_contracts = await ib.qualifyContractsAsync(*contracts)

            tickers_dict = {}
            for contract in qualified_contracts:
                t = ib.reqMktData(contract, "100,101,104,106,233,236", snapshot=False)
                tickers_dict[contract] = t

            start = time.time()
            while time.time() - start < 10:
                if all(t.domBids and t.domAsks for t in tickers_dict.values() if t.domBids is not None):
                    break
                await asyncio.sleep(0.5)

            updated_tickers = await ib.reqTickersAsync(*qualified_contracts)

            for contract in qualified_contracts:
                ib.cancelMktData(contract)

            # Reset lists
            for lst in [strikes, call_ints, put_ints, call_volumes, put_volumes, call_gammas, put_gammas, call_deltas, put_deltas,
                        call_premiums, put_premiums, call_ivs, put_ivs, call_bid_ivs, call_ask_ivs, put_bid_ivs, put_ask_ivs,
                        call_thetas, put_thetas, call_vegas, put_vegas, call_vol_at_bid, call_vol_at_ask, put_vol_at_bid, put_vol_at_ask,
                        slp_values]:  # إضافة slp_values
                lst[:] = [0.0 if isinstance(lst[0], float) else 0] * N_STRIKES

            temp_data = {s: {'call': {}, 'put': {}} for s in temp_strikes_list}

            for strike in temp_strikes_list:
                call_ticker = next((t for t in updated_tickers if t.contract.strike == strike and t.contract.right == 'C'), None)
                put_ticker = next((t for t in updated_tickers if t.contract.strike == strike and t.contract.right == 'P'), None)

                if call_ticker:
                    oi = call_ticker.callOpenInterest
                    vol = call_ticker.volume
                    call_open_interest = int(oi) if oi and not isnan(oi) else 0
                    call_volume = int(vol) if vol and not isnan(vol) else 0
                    gamma = call_ticker.modelGreeks.gamma if call_ticker.modelGreeks and call_ticker.modelGreeks.gamma else 0.0099
                    delta = call_ticker.modelGreeks.delta if call_ticker.modelGreeks and call_ticker.modelGreeks.delta else 0.7427
                    theta = call_ticker.modelGreeks.theta if call_ticker.modelGreeks and call_ticker.modelGreeks.theta else 0.0
                    iv = call_ticker.modelGreeks.impliedVol if call_ticker.modelGreeks and call_ticker.modelGreeks.impliedVol else 0.0
                    vega = call_ticker.modelGreeks.vega if call_ticker.modelGreeks and call_ticker.modelGreeks.vega else 0.0
                    call_premium = call_ticker.last or ((call_ticker.bid + call_ticker.ask) / 2 if call_ticker.bid and call_ticker.ask else 0)
                    call_bid_iv = call_ticker.bidGreeks.impliedVol if call_ticker.bidGreeks and hasattr(call_ticker.bidGreeks, 'impliedVol') and call_ticker.bidGreeks.impliedVol else 0.0
                    call_ask_iv = call_ticker.askGreeks.impliedVol if call_ticker.askGreeks and hasattr(call_ticker.askGreeks, 'impliedVol') and call_ticker.askGreeks.impliedVol else 0.0

                    # تحسين: تقدير Vega إذا كانت 0 وIV > 0
                    if vega == 0 and iv > 0:
                        try:
                            d1 = (log(spx_price / strike) + (r_rate - q_yield + iv**2 / 2) * T) / (iv * sqrt(T))
                            vega = spx_price * sqrt(T) * norm.pdf(d1) / 100
                            logging.info(f"تم تقدير Vega لـ Call {strike}: {vega:.4f}")
                        except Exception as est_error:
                            logging.warning(f"فشل تقدير Vega لـ Call {strike}: {est_error}")
                            vega = 0.0

                    dom_ticker = tickers_dict.get(call_ticker.contract)
                    call_vol_bid = dom_ticker.domBids[0].size if dom_ticker and dom_ticker.domBids and len(dom_ticker.domBids) > 0 else 0
                    call_vol_ask = dom_ticker.domAsks[0].size if dom_ticker and dom_ticker.domAsks and len(dom_ticker.domAsks) > 0 else 0

                    temp_data[strike]['call'] = {
                        'oi': call_open_interest, 'vol': call_volume, 'gamma': gamma, 'delta': delta,
                        'theta': theta, 'vega': vega, 'premium': call_premium, 'iv': iv,
                        'bid_iv': call_bid_iv, 'ask_iv': call_ask_iv, 'vol_bid': call_vol_bid, 'vol_ask': call_vol_ask
                    }
                else:
                    temp_data[strike]['call'] = {k: 0 for k in ['oi', 'vol', 'gamma', 'delta', 'theta', 'vega', 'premium', 'iv', 'bid_iv', 'ask_iv', 'vol_bid', 'vol_ask']}

                if put_ticker:
                    oi = put_ticker.putOpenInterest
                    vol = put_ticker.volume
                    put_open_interest = int(oi) if oi and not isnan(oi) else 0
                    put_volume = int(vol) if vol and not isnan(vol) else 0
                    gamma = put_ticker.modelGreeks.gamma if put_ticker.modelGreeks and put_ticker.modelGreeks.gamma else 0.0099
                    delta = put_ticker.modelGreeks.delta if put_ticker.modelGreeks and put_ticker.modelGreeks.delta else -0.2573
                    theta = put_ticker.modelGreeks.theta if put_ticker.modelGreeks and put_ticker.modelGreeks.theta else 0.0
                    iv = put_ticker.modelGreeks.impliedVol if put_ticker.modelGreeks and put_ticker.modelGreeks.impliedVol else 0.0
                    vega = put_ticker.modelGreeks.vega if put_ticker.modelGreeks and put_ticker.modelGreeks.vega else 0.0
                    put_premium = put_ticker.last or ((put_ticker.bid + put_ticker.ask) / 2 if put_ticker.bid and put_ticker.ask else 0)
                    put_bid_iv = put_ticker.bidGreeks.impliedVol if put_ticker.bidGreeks and hasattr(put_ticker.bidGreeks, 'impliedVol') and put_ticker.bidGreeks.impliedVol else 0.0
                    put_ask_iv = put_ticker.askGreeks.impliedVol if put_ticker.askGreeks and hasattr(put_ticker.askGreeks, 'impliedVol') and put_ticker.askGreeks.impliedVol else 0.0

                    # تحسين: تقدير Vega إذا كانت 0 وIV > 0
                    if vega == 0 and iv > 0:
                        try:
                            d1 = (log(spx_price / strike) + (r_rate - q_yield + iv**2 / 2) * T) / (iv * sqrt(T))
                            vega = spx_price * sqrt(T) * norm.pdf(d1) / 100
                            logging.info(f"تم تقدير Vega لـ Put {strike}: {vega:.4f}")
                        except Exception as est_error:
                            logging.warning(f"فشل تقدير Vega لـ Put {strike}: {est_error}")
                            vega = 0.0

                    dom_ticker = tickers_dict.get(put_ticker.contract)
                    put_vol_bid = dom_ticker.domBids[0].size if dom_ticker and dom_ticker.domBids and len(dom_ticker.domBids) > 0 else 0
                    put_vol_ask = dom_ticker.domAsks[0].size if dom_ticker and dom_ticker.domAsks and len(dom_ticker.domAsks) > 0 else 0

                    temp_data[strike]['put'] = {
                        'oi': put_open_interest, 'vol': put_volume, 'gamma': gamma, 'delta': delta,
                        'theta': theta, 'vega': vega, 'premium': put_premium, 'iv': iv,
                        'bid_iv': put_bid_iv, 'ask_iv': put_ask_iv, 'vol_bid': put_vol_bid, 'vol_ask': put_vol_ask
                    }
                else:
                    temp_data[strike]['put'] = {k: 0 for k in ['oi', 'vol', 'gamma', 'delta', 'theta', 'vega', 'premium', 'iv', 'bid_iv', 'ask_iv', 'vol_bid', 'vol_ask']}

            above_data = sorted([s for s in temp_strikes_list if s > spx_price], reverse=True)[:15]
            below_data = sorted([s for s in temp_strikes_list if s < spx_price])[:15]

            for i, strike in enumerate(above_data + below_data):
                if i >= N_STRIKES:
                    break
                c = temp_data[strike]['call']
                p = temp_data[strike]['put']
                strikes[i] = strike
                call_ints[i] = c['oi']
                put_ints[i] = p['oi']
                call_volumes[i] = c['vol']
                put_volumes[i] = p['vol']
                call_gammas[i] = c['gamma']
                put_gammas[i] = p['gamma']
                call_deltas[i] = c['delta']
                put_deltas[i] = p['delta']
                call_premiums[i] = c['premium']
                put_premiums[i] = p['premium']
                call_ivs[i] = c['iv']
                put_ivs[i] = p['iv']
                call_bid_ivs[i] = c['bid_iv']
                call_ask_ivs[i] = c['ask_iv']
                put_bid_ivs[i] = p['bid_iv']
                put_ask_ivs[i] = p['ask_iv']
                call_thetas[i] = c['theta']
                put_thetas[i] = p['theta']
                call_vegas[i] = c['vega']
                put_vegas[i] = p['vega']
                call_vol_at_bid[i] = c['vol_bid']
                call_vol_at_ask[i] = c['vol_ask']
                put_vol_at_bid[i] = p['vol_bid']
                put_vol_at_ask[i] = p['vol_ask']

            last_request_time = current_time
            self.update_auto_table()
            self.analyze_data()
        except Exception as e:
            error_msg = f"فشل جلب بيانات الـOptions: {str(e)}"
            self.status_bar.showMessage(error_msg)
            logging.error(error_msg, exc_info=True)

    def safe_fmt(self, val, fmt_str, default="N/A"):
        if val is None or (isinstance(val, float) and isnan(val)):
            return default
        try:
            return fmt_str.format(val)
        except:
            return default

    def update_auto_table(self):
        for i in range(N_STRIKES):
            if strikes[i] <= 0:
                continue

            item = QTableWidgetItem(self.safe_fmt(call_premiums[i], "{:.2f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 0, item)

            item = QTableWidgetItem(str(call_volumes[i]))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 1, item)

            item = QTableWidgetItem(self.safe_fmt(call_bid_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 2, item)

            item = QTableWidgetItem(self.safe_fmt(call_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFC0CB"))
            self.auto_table.setItem(i, 3, item)

            item = QTableWidgetItem(self.safe_fmt(call_ask_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 4, item)

            item = QTableWidgetItem(str(call_ints[i]))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 5, item)

            item = QTableWidgetItem(self.safe_fmt(call_deltas[i], "{:.4f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 6, item)

            item = QTableWidgetItem(self.safe_fmt(call_gammas[i], "{:.4f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 7, item)

            item_strike = QTableWidgetItem(str(strikes[i]))
            item_strike.setTextAlignment(Qt.AlignCenter)
            item_strike.setFont(QFont("Arial", 12, QFont.Bold))
            self.auto_table.setItem(i, 8, item_strike)

            item = QTableWidgetItem(self.safe_fmt(put_gammas[i], "{:.4f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 9, item)

            item = QTableWidgetItem(self.safe_fmt(put_deltas[i], "{:.4f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 10, item)

            item = QTableWidgetItem(str(put_ints[i]))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 11, item)

            item = QTableWidgetItem(self.safe_fmt(put_ask_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 12, item)

            item = QTableWidgetItem(self.safe_fmt(put_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFC0CB"))
            self.auto_table.setItem(i, 13, item)

            item = QTableWidgetItem(self.safe_fmt(put_bid_ivs[i], "{:.2%}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 14, item)

            item = QTableWidgetItem(str(put_volumes[i]))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#FFFFFF"))
            self.auto_table.setItem(i, 15, item)

            item = QTableWidgetItem(self.safe_fmt(put_premiums[i], "{:.2f}"))
            item.setTextAlignment(Qt.AlignCenter)
            item.setForeground(QColor("#87CEFA"))
            self.auto_table.setItem(i, 16, item)

    # دالة محسنة لـ Z-scores باستخدام caching (تحسين)
    @lru_cache(maxsize=128)
    def compute_z_scores_cached(self, data_key, timestamp_key):
        # data_key: tuple من القوائم
        # timestamp_key: لإبطال الـ cache كل 5 دقائق
        net_gex_list, delta_vol_list, vol_imb_list, iv_skew_list, vanna_align_list, rv_ratio_list = data_key
        z_scores = []
        lists = [net_gex_list, delta_vol_list, vol_imb_list, iv_skew_list, vanna_align_list, rv_ratio_list]
        for lst in lists:
            if len(lst) > 1:
                z = stats.zscore(lst)
            else:
                z = [0.0] * len(lst)
            z_scores.append(z)
        return tuple(z_scores)

    def analyze_data(self, filter_type="All"):
        global strikes, call_ints, put_ints, call_volumes, put_volumes, call_gammas, put_gammas, call_deltas, put_deltas, current_price, pcr_history, call_premiums, put_premiums, expiration_date, call_thetas, put_thetas, call_vegas, put_vegas, r_rate, q_yield, call_vol_at_bid, call_vol_at_ask, put_vol_at_bid, put_vol_at_ask, slp_values, weights, vol_history
        try:
            data = []
            contract_size = 100
            call_gex_total = 0
            put_gex_total = 0
            call_dwoi_total = 0
            put_dwoi_total = 0
            total_call_volume = sum(call_volumes)
            total_put_volume = sum(put_volumes)
            total_call_oi = sum(call_ints)
            total_put_oi = sum(put_ints)
            volume_pcr = "N/A"
            oi_pcr = "N/A"
            if total_call_volume > 0:
                volume_pcr = round(total_put_volume / total_call_volume, 2)
            if total_call_oi > 0:
                oi_pcr = round(total_put_oi / total_call_oi, 2)

            pcr_history.append((volume_pcr, oi_pcr))
            if len(pcr_history) > 5:
                pcr_history.pop(0)

            self.strike_recommendations = []
            self.net_flow_values = []
            self.pro_flow_values = []
            avg_iv = 0.0
            valid_ivs = [iv for iv in call_ivs + put_ivs if iv > 0]
            if valid_ivs:
                avg_iv = sum(valid_ivs) / len(valid_ivs)

            if expiration_date:
                today = datetime.now()
                t_days = max((expiration_date - today).days, 1)
            else:
                t_days = 30

            em_value = current_price * avg_iv * sqrt(t_days / 365)
            em_range = f"{round(current_price - em_value, 2)} - {round(current_price + em_value, 2)}"
            em_recommendation = f"EM Range (1σ, {t_days} days): {em_range}"

            trading_hours = 6.5
            num_half_hours = trading_hours * 2
            gamma_levels_list = [] 

            # حساب GAMMA PEAK و CEILING قبل الحلقة
            gamma_peak_strike = 0
            gamma_ceiling_strike = 0
            gamma_peak_value = 0
            gamma_ceiling_value = 0

            for j in range(N_STRIKES):
                if strikes[j] <= 0:
                    continue
                gex = (call_gammas[j] * call_ints[j] - put_gammas[j] * put_ints[j]) * current_price
                if strikes[j] < current_price and abs(gex) > abs(gamma_peak_value):
                    gamma_peak_value = gex
                    gamma_peak_strike = strikes[j]
                if strikes[j] > current_price and abs(gex) > abs(gamma_ceiling_value):
                    gamma_ceiling_value = gex
                    gamma_ceiling_strike = strikes[j]

            # IV SKEW
            valid_put_ivs = [iv for iv in put_ivs if iv > 0]
            valid_call_ivs = [iv for iv in call_ivs if iv > 0]
            tail_risk = (max(valid_put_ivs) - min(valid_call_ivs)) * 10 if valid_put_ivs and valid_call_ivs else 0

            otm_put_ivs = [iv for iv in put_ivs[:15] if iv > 0]
            otm_call_ivs = [iv for iv in call_ivs[15:] if iv > 0]
            avg_put_iv = sum(otm_put_ivs) / len(otm_put_ivs) if otm_put_ivs else 0
            avg_call_iv = sum(otm_call_ivs) / len(otm_call_ivs) if otm_call_ivs else 0
            iv_skew = avg_put_iv - avg_call_iv

            # قوائم لـ SLP_t
            net_gex_list = []
            delta_vol_list = []
            vol_imb_list = []
            iv_skew_list = [iv_skew] * N_STRIKES  # IV Skew عام للبساطة
            vanna_align_list = []
            rv_ratio_list = []

            # نظام الوزن
            direction_weights = {
                'VWGF': 3, 'PF': 3, 'G': 2, 'D': 2, 'F': 1, 'V': 1, 'O': 1, 'SAGE': 4, 'GFPI': 3, 'VAGPFI': 4
            }
            risk_weights = {
                'TR': 3, 'SK': 2, 'VE': 2, 'VANNA': 2, 'GNI': 1, 'T': 1, 'Charm': 1, 'SAGE': 3, 'GFPI': 2, 'VAGPFI': 3
            }

            for i in range(N_STRIKES):
                if strikes[i] <= 0:
                    gamma_levels_list.append(0.0)
                    net_gex_list.append(0.0)
                    delta_vol_list.append(0.0)
                    vol_imb_list.append(0.0)
                    vanna_align_list.append(0.0)
                    rv_ratio_list.append(0.0)
                    continue

                # تحديث vol_history
                total_vol = call_volumes[i] + put_volumes[i]
                vol_history[i].pop(0)  # إزالة الأقدم
                vol_history[i].append(total_vol)

                # ΔVol_{±3} (متوسط التغير في آخر 3)
                delta_vol = sum(vol_history[i][j] - vol_history[i][j-1] for j in range(1, len(vol_history[i]))) if len(vol_history[i]) > 1 else 0
                delta_vol_list.append(delta_vol)

                net_flow = (call_volumes[i] * call_premiums[i]) - (put_volumes[i] * put_premiums[i])
                self.net_flow_values.append(net_flow)

                aggressive_call_buy = call_vol_at_ask[i] * call_premiums[i]
                aggressive_put_buy = put_vol_at_bid[i] * put_premiums[i]
                aggressive_flow = aggressive_call_buy - aggressive_put_buy

                delta_weighted_call = call_volumes[i] * abs(call_deltas[i]) * call_premiums[i]
                delta_weighted_put = put_volumes[i] * abs(put_deltas[i]) * put_premiums[i]
                delta_flow = delta_weighted_call - delta_weighted_put

                pro_flow = aggressive_flow + delta_flow
                self.pro_flow_values.append(pro_flow)

                # GEX+ المحسن
                epsilon = 0.01
                spot_diff = current_price - strikes[i]
                spot_adjust = spot_diff / (abs(spot_diff) + epsilon)
                delta_sens = abs(call_deltas[i]) if call_deltas[i] != 0 else abs(put_deltas[i])
                net_gex_raw = (call_gammas[i] * call_ints[i] - put_gammas[i] * put_ints[i]) * 100
                net_gex = net_gex_raw * spot_adjust * delta_sens
                net_gex_list.append(-net_gex)  # -GEX لـ SLP_t
                call_gex = call_gammas[i] * call_ints[i] * contract_size * current_price
                put_gex = put_gammas[i] * put_ints[i] * contract_size * current_price * -1
                call_gex_total += call_gex
                put_gex_total += put_gex

                # DWOI+ المحسن
                spot_adjust = spot_diff / (abs(spot_diff) + epsilon)
                t_days_local = max((expiration_date - datetime.now()).days, 1) if expiration_date else 30
                time_weight = exp(-0.01 * t_days_local / 365)

                call_dwoi_raw = call_deltas[i] * call_ints[i] * contract_size
                put_dwoi_raw = put_deltas[i] * put_ints[i] * contract_size * -1

                call_dwoi = call_dwoi_raw * spot_adjust * time_weight
                put_dwoi = put_dwoi_raw * spot_adjust * time_weight

                call_dwoi_total += call_dwoi
                put_dwoi_total += put_dwoi
                net_dwoi = call_dwoi + put_dwoi

                call_theta_decay = call_thetas[i] * contract_size if call_thetas[i] is not None else 0.0
                put_theta_decay = put_thetas[i] * contract_size if put_thetas[i] is not None else 0.0
                net_theta_decay = call_theta_decay + put_theta_decay
                theta_dir = "Call" if net_theta_decay > 0 else "Put"
                theta_half_hour = net_theta_decay / num_half_hours if num_half_hours > 0 else 0.0
                theta_display = f"{round(net_theta_decay, 2)} / {round(theta_half_hour, 2)} h"

                call_vega_exposure = call_vegas[i] * contract_size if call_vegas[i] is not None else 0.0
                put_vega_exposure = put_vegas[i] * contract_size if put_vegas[i] is not None else 0.0
                net_vega = call_vega_exposure + put_vega_exposure
                vega_dir = "Call" if net_vega > 0 else "Put"

                call_vanna = call_gammas[i] * (call_vegas[i] / (current_price * max(call_ivs[i], 0.01))) * (r_rate - q_yield) if call_ivs[i] > 0 else 0.0
                put_vanna = put_gammas[i] * (put_vegas[i] / (current_price * max(put_ivs[i], 0.01))) * (r_rate - q_yield) if put_ivs[i] > 0 else 0.0
                net_vanna = (call_vanna + put_vanna) * 100000
                vanna_align = net_vanna * (current_price / strikes[i]) if strikes[i] > 0 else net_vanna  # محاذاة بسيطة مع السعر
                vanna_align_list.append(vanna_align)

                call_charm = (-call_thetas[i] / (365 * current_price) + call_gammas[i] * r_rate) * 1000 if call_thetas[i] is not None else 0.0
                put_charm = (-put_thetas[i] / (365 * current_price) + put_gammas[i] * r_rate) * 1000 if put_thetas[i] is not None else 0.0
                net_charm = call_charm + put_charm

                gni = net_gex / abs(net_dwoi) if net_dwoi != 0 else 0

                gamma_levels = (call_gammas[i] * call_ints[i] - put_gammas[i] * put_ints[i]) * current_price
                gamma_levels_list.append(gamma_levels)

                # VolImb
                vol_imb = (call_volumes[i] - put_volumes[i]) / (call_volumes[i] + put_volumes[i] + 1e-6) if (call_volumes[i] + put_volumes[i]) > 0 else 0
                vol_imb_list.append(vol_imb)

                # RVratio (تقريبي: IV / افتراضي 1.0؛ يمكن تحسين بتاريخ أسعار)
                rv_ratio = avg_iv / 1.0 if avg_iv > 0 else 1.0
                rv_ratio_list.append(rv_ratio)

                # VWGF+ المحسن
                aggressive_call = call_vol_at_ask[i] * call_deltas[i] * call_gammas[i]
                aggressive_put = put_vol_at_bid[i] * abs(put_deltas[i]) * put_gammas[i]
                aggressive_flow = aggressive_call - aggressive_put

                spot_weight = 1 / (abs(current_price - strikes[i]) + 0.01)
                v_w_gamma_flow = (aggressive_flow / max(current_price, 1)) * spot_weight
                v_w_gamma_flow_dir = "Call" if v_w_gamma_flow > 0 else "Put"

                try:
                    # SAGE
                    epsilon = 0.01
                    spot_diff = current_price - strikes[i]
                    spot_adjust = spot_diff / (abs(spot_diff) + epsilon)
                    delta_sens = abs(call_deltas[i]) if call_deltas[i] != 0 else abs(put_deltas[i])
                    sage = net_gex * spot_adjust * delta_sens
                    sage_dir = "Call" if sage > 0 else "Put"

                    # GFPI
                    charm_net = net_charm
                    vega_net = net_vega
                    call_vol_ask_term = call_vol_at_ask[i] * abs(call_deltas[i]) * call_gammas[i]
                    put_vol_bid_term = put_vol_at_bid[i] * abs(put_deltas[i]) * put_gammas[i] * (1 + abs(iv_skew))
                    gfp_i = (charm_net * vega_net + (call_vol_ask_term - put_vol_bid_term)) / max(current_price, 1)
                    distance_to_cluster = min(abs(strikes[i] - gamma_peak_strike), abs(strikes[i] - gamma_ceiling_strike)) if gamma_peak_strike and gamma_ceiling_strike else abs(current_price - strikes[i])
                    gfpi = gfp_i / sqrt(distance_to_cluster + epsilon)
                    gfpi_dir = "Call" if gfpi > 0 else "Put"

                    # VAGPFI
                    charm_net = net_charm
                    vega_net = net_vega
                    call_vol_ask_vag = call_vol_at_ask[i] * abs(call_deltas[i]) * call_gammas[i]
                    put_vol_bid_vag = put_vol_at_bid[i] * abs(put_deltas[i]) * put_gammas[i] * (1 + abs(iv_skew))
                    vagpfi_numerator = (charm_net * vega_net + (call_vol_ask_vag - put_vol_bid_vag)) / max(current_price, 1)
                    vagpfi_denominator = sqrt(abs(distance_to_cluster) + epsilon * t_days / 365)
                    vagpfi = vagpfi_numerator / vagpfi_denominator
                    vagpfi_dir = "Call" if vagpfi > 0 else "Put"
                except Exception as calc_error:
                    logging.error(f"خطأ في SAGE/GFPI/VAGPFI لـstrike {strikes[i]}: {calc_error}")
                    sage = 0.0
                    gfpi = 0.0
                    vagpfi = 0.0
                    sage_dir = "Neutral"
                    gfpi_dir = "Neutral"
                    vagpfi_dir = "Neutral"

                gex_dir = "Call" if net_gex > 0 else "Put"
                dwoi_dir = "Call" if net_dwoi > 0 else "Put"
                volume_pcr_dir = "Call" if volume_pcr != "N/A" and volume_pcr < 1 else "Put"
                oi_pcr_dir = "Call" if oi_pcr != "N/A" and oi_pcr < 1 else "Put"
                net_flow_dir = "Call" if net_flow > 0 else "Put"
                pro_flow_dir = "Call" if pro_flow > 0 else "Put"
                skew_dir = "Put" if iv_skew > 0.05 else "Call" if iv_skew < -0.05 else "Neutral"
                tail_dir = "Put" if tail_risk > 130 else "Call"
                theta_dir = "Call" if net_theta_decay > 0 else "Put"
                vega_dir = "Call" if net_vega > 0 else "Put"

                directions = {
                    'G': gex_dir,
                    'D': dwoi_dir,
                    'V': volume_pcr_dir,
                    'O': oi_pcr_dir,
                    'F': net_flow_dir,
                    'PF': pro_flow_dir,
                    'T': theta_dir,
                    'VE': vega_dir,
                    'SK': skew_dir,
                    'TR': tail_dir,
                    'VWGF': v_w_gamma_flow_dir,
                    'SAGE': sage_dir,
                    'GFPI': gfpi_dir,
                    'VAGPFI': vagpfi_dir
                }

                # === وزن الاتجاهي المحلي (لكل Strike) ===
                call_weight_local = sum(direction_weights.get(key, 1) for key, dir_val in directions.items() if dir_val == "Call")
                put_weight_local = sum(direction_weights.get(key, 1) for key, dir_val in directions.items() if dir_val == "Put")
                total_dir_weight_local = call_weight_local + put_weight_local
                dir_percentage_local = ((call_weight_local - put_weight_local) / total_dir_weight_local * 100) if total_dir_weight_local > 0 else 0

                # === وزن المخاطر المحلي (لكل Strike) ===
                risk_map_local = {
                    'TR': tail_risk > 130, 'SK': iv_skew > 0.05, 'VE': abs(net_vega) > 100000,
                    'VANNA': abs(net_vanna) > 50000, 'GNI': abs(gni) > 1, 'T': abs(net_theta_decay) > 1000,
                    'Charm': abs(net_charm) > 100, 'SAGE': abs(sage) > 5000, 'GFPI': abs(gfpi) > 1, 'VAGPFI': abs(vagpfi) > 1
                }
                low_risk_weight_local = sum(risk_weights.get(key, 1) for key, is_high in risk_map_local.items() if not is_high)
                high_risk_weight_local = sum(risk_weights.get(key, 1) for key, is_high in risk_map_local.items() if is_high)
                total_risk_weight_local = low_risk_weight_local + high_risk_weight_local
                risk_percentage_local = ((low_risk_weight_local - high_risk_weight_local) / total_risk_weight_local * 100) if total_risk_weight_local > 0 else 0

                call_count = sum(1 for v in directions.values() if v == "Call")
                put_count = sum(1 for v in directions.values() if v == "Put")
                consensus_dir = "Call" if call_count > put_count else "Put"
                strength = f"{call_count}/14 Call" if consensus_dir == "Call" else f"{put_count}/14 Put"
                signal_letters = [letter for letter, dir_val in directions.items() if dir_val == consensus_dir]

                self.strike_recommendations.append((consensus_dir, signal_letters, strikes[i], strength, dir_percentage_local, risk_percentage_local))

                data.append({
                    "Strike": strikes[i],
                    "PRO FLOW": pro_flow,
                    "FLOW": net_flow,
                    "Volume PCR": volume_pcr,
                    "DWOI": net_dwoi,
                    "GEX": net_gex,
                    "OI PCR": oi_pcr,
                    "TAIL RISK": tail_risk,
                    "IV SKEW": iv_skew,
                    "VEGA": net_vega,
                    "VANNA": net_vanna,
                    "GNI": gni,
                    "Theta Decay": theta_display,
                    "Charm": net_charm,
                    "FLIP LEVEL": None,
                    "GAMMA LEVELS": gamma_levels,
                    "EM Range": em_range,
                    "VWGF": v_w_gamma_flow,
                    "SAGE": sage,
                    "GFPI": gfpi,
                    "VAGPFI": vagpfi,
                    "SLP_T": 0.0,  # سيتم حسابه لاحقًا
                    "Direction": consensus_dir,
                    "Strength": strength,
                    "dir_percentage": dir_percentage_local,
                    "risk_percentage": risk_percentage_local
                })

            # حساب Z-scores باستخدام الـ cache (تحسين)
            if len(net_gex_list) > 1:
                data_key = (tuple(net_gex_list), tuple(delta_vol_list), tuple(vol_imb_list), tuple(iv_skew_list), tuple(vanna_align_list), tuple(rv_ratio_list))
                current_timestamp = int(time.time() / 300)  # إبطال كل 5 دقائق
                z_result = self.compute_z_scores_cached(data_key, current_timestamp)
                z_gex, z_delta_vol, z_vol_imb, z_iv_skew, z_vanna_align, z_rv_ratio = z_result

                for i in range(N_STRIKES):
                    if strikes[i] > 0:
                        slp = (weights[0] * z_gex[i] + weights[1] * z_delta_vol[i] + weights[2] * z_vol_imb[i] +
                               weights[3] * z_iv_skew[i] + weights[4] * z_vanna_align[i] - weights[5] * z_rv_ratio[i])
                        slp_values[i] = round(slp, 2)
                        data[i]["SLP_T"] = slp_values[i]

            # Flip Level المحسن (مع التعديل: ترتيب تصاعدي للاسترايك)
            valid_pairs = [(strikes[i], gamma_levels_list[i], call_ints[i] + put_ints[i]) for i in range(N_STRIKES) if strikes[i] > 0]
            valid_pairs.sort(key=lambda x: x[0])  # ترتيب تصاعدي حسب strike
            if valid_pairs:
                sorted_strikes, sorted_gamma, sorted_oi = zip(*valid_pairs)
            else:
                sorted_strikes = []
                sorted_gamma = []
                sorted_oi = []

            best_flip = None
            best_strength = 0.0

            for j in range(len(sorted_gamma) - 1):
                gex_curr = sorted_gamma[j]
                gex_next = sorted_gamma[j + 1]
                if gex_curr * gex_next < 0:
                    oi_weight = (sorted_oi[j] + sorted_oi[j + 1]) / 2
                    strength = abs(gex_curr - gex_next) * oi_weight
                    if strength > best_strength:
                        best_strength = strength
                        flip = sorted_strikes[j] + (sorted_strikes[j + 1] - sorted_strikes[j]) * (0 - gex_curr) / (gex_next - gex_curr)
                        best_flip = round(flip, 1)

            flip_level = best_flip

            # Tail Risk+ المحسن
            atm_strike = min(strikes, key=lambda x: abs(x - current_price)) if strikes else 0
            atm_iv = next(((call_ivs[i] + put_ivs[i]) / 2 for i in range(N_STRIKES) if strikes[i] == atm_strike and call_ivs[i] > 0 and put_ivs[i] > 0), 0.2)

            tail_risk_plus = 0.0
            epsilon = 0.01

            for i in range(N_STRIKES):
                if strikes[i] <= 0:
                    continue
                spot_diff = current_price - strikes[i]
                spot_weight = 1 / (abs(spot_diff) + epsilon)

                if strikes[i] < current_price * 0.9 or strikes[i] > current_price * 1.1:
                    iv_diff = abs(call_ivs[i] - atm_iv) + abs(put_ivs[i] - atm_iv)
                    oi_weight = (call_ints[i] + put_ints[i]) / 2
                    tail_risk_plus += iv_diff * oi_weight * spot_weight

            tail_risk = round(tail_risk_plus, 0)

            if not data:
                self.status_bar.showMessage("لا بيانات للتحليل؛ تحقق من الستريكات أو الغريكس.")
                logging.warning("data فارغة؛ تحقق من الحلقة.")
                return

            spx_price = current_price
            try:
                manual_spx = float(self.manual_price_input.text())
                if manual_spx > 0:
                    spx_price = manual_spx
                    current_price = spx_price
                    self.spx_price_label.setText(f"سعر SPX الحالي (يدوي): {spx_price}")
            except:
                pass

            if spx_price == 0:
                self.status_bar.showMessage("جلب سعر SPX تلقائيًا أو أدخل سعر يدويًا")
                logging.warning("سعر SPX غير متاح")
                return

            if filter_type != "All":
                data = [d for d in data if d["Direction"] == filter_type]

            results = []
            for d in data:
                d["FLIP LEVEL"] = flip_level
                d["TAIL RISK"] = tail_risk
                results.append(d)

            results.sort(key=lambda x: x["Strike"], reverse=True)
            self.strike_recommendations.sort(key=lambda x: x[2], reverse=True)

            # === عرض التوصيات النهائية ===
            for i in range(N_STRIKES):
                if i < len(results):
                    res = results[i]
                    values = [
                        str(res["Strike"]),
                        f"{res['PRO FLOW']:,.0f}",
                        f"{res['FLOW']:,.0f}",
                        str(res["Volume PCR"]),
                        f"{res['DWOI']:,.0f}",
                        f"{res['GEX']:,.0f}",
                        str(res["OI PCR"]),
                        f"{res['TAIL RISK']:.0f}",
                        f"{res['IV SKEW']:.1%}",
                        f"{res['VEGA']:,.0f}",
                        f"{res['VANNA']:,.0f}",
                        f"{res['GNI']:.2f}",
                        res["Theta Decay"],
                        f"{res['Charm']:.2f}",
                        "N/A",
                        f"{res['GAMMA LEVELS']:,.0f}",
                        res["EM Range"],
                        f"{res['VWGF']:.4f}",
                        f"{res['SAGE']:,.0f}",
                        f"{res['GFPI']:.4f}",
                        f"{res['VAGPFI']:.4f}",
                        f"{res['SLP_T']:.2f}"  # إضافة SLP_t
                    ]
                    for col, value in enumerate(values):
                        item = QTableWidgetItem(value)
                        item.setTextAlignment(Qt.AlignCenter)

                        # تحديد اللون حسب العمود (نفس الأصلي)
                        if col == 1:  # PRO FLOW
                            val = res.get("PRO FLOW", 0)
                            item.setForeground(QColor("lime") if val > 0 else QColor("red"))
                        elif col == 2:  # FLOW
                            val = res.get("FLOW", 0)
                            item.setForeground(QColor("lime") if val > 0 else QColor("red"))
                        elif col == 5:  # GEX
                            val = res.get("GEX", 0)
                            item.setForeground(QColor("lime") if val > 0 else QColor("red"))
                        elif col == 17:  # VWGF
                            val = res.get("VWGF", 0)
                            item.setForeground(QColor("cyan") if val > 0 else QColor("pink"))
                        elif col == 18:  # SAGE
                            val = res.get("SAGE", 0)
                            item.setForeground(QColor("gold") if abs(val) > 5000 else QColor("silver"))
                            if abs(val) > 10000:
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                        elif col == 19:  # GFPI
                            val = res.get("GFPI", 0)
                            item.setForeground(QColor("cyan") if val > 0 else QColor("magenta"))
                            if abs(val) > 1:
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                        elif col == 20:  # VAGPFI
                            val = res.get("VAGPFI", 0)
                            item.setForeground(QColor("lightgreen") if val > 0 else QColor("lightcoral"))
                            if abs(val) > 1:
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                        elif col == 21:  # SLP_t الجديد
                            val = res.get("SLP_T", 0)
                            item.setForeground(QColor("lime") if val > 0 else QColor("red"))
                            if abs(val) > 1.0:  # عتبة للإبراز
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                        elif col == 16:  # EM Range
                            item.setForeground(QColor("yellow"))
                        elif col == 7:  # TAIL RISK
                            item.setForeground(QColor("orange"))
                        elif col == 8:  # IV SKEW
                            item.setForeground(QColor("magenta"))
                        elif col == 13:  # Charm
                            val = res.get("Charm", 0)
                            item.setForeground(QColor("lime") if val > 0 else QColor("red"))
                        elif col == 11:  # GNI
                            val = res.get("GNI", 0)
                            item.setForeground(QColor("lime") if val > 1 else QColor("red"))
                        elif col == 6:  # OI PCR
                            val = res.get("OI PCR", 0)
                            if isinstance(val, (int, float)):
                                item.setForeground(QColor("lime") if val < 1 else QColor("red"))
                            else:
                                item.setForeground(QColor("yellow"))
                        elif col == 3:  # Volume PCR
                            val = res.get("Volume PCR", 0)
                            if isinstance(val, (int, float)):
                                item.setForeground(QColor("lime") if val < 1 else QColor("red"))
                            else:
                                item.setForeground(QColor("yellow"))
                        elif col == 15:  # GAMMA LEVELS
                            if res["Strike"] == gamma_peak_strike:
                                item.setForeground(QColor("lime"))
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                            elif res["Strike"] == gamma_ceiling_strike:
                                item.setForeground(QColor("red"))
                                item.setFont(QFont("Arial", 10, QFont.Bold))
                            else:
                                item.setForeground(QColor("yellow"))
                        else:
                            item.setForeground(QColor("#FFFFFF" if current_theme == "Dark" else "#000000"))

                        self.table.setItem(i, col, item)
                else:
                    for col in range(22):  # تحديث لـ 22 عمود
                        item = QTableWidgetItem("N/A")
                        item.setTextAlignment(Qt.AlignCenter)
                        self.table.setItem(i, col, item)

            # === عرض FLIP LEVEL في أعلى 3 صفوف فقط ===
            flip_str = f"{flip_level:.0f}" if flip_level else "N/A"
            flip_color = QColor("lime") if current_price > (flip_level or 0) else QColor("red")
            for row in range(min(3, len(results))):
                flip_item = QTableWidgetItem(flip_str)
                flip_item.setTextAlignment(Qt.AlignCenter)
                flip_item.setForeground(flip_color)
                flip_item.setFont(QFont("Arial", 10, QFont.Bold))
                self.table.setItem(row, 14, flip_item)

            # === تبويب التوصيات الجديد (معدل) ===
            self.eq_table.clearContents()
            self.eq_table.setRowCount(12)

            top_calls = sorted([r for r in self.strike_recommendations if r[0] == "Call"], key=lambda x: x[3], reverse=True)[:6]
            top_puts = sorted([r for r in self.strike_recommendations if r[0] == "Put"], key=lambda x: x[3], reverse=True)[:6]

            row = 0
            for recom in top_calls + top_puts:
                consensus_dir, _, strike, strength, dir_percentage_local, risk_percentage_local = recom

                # Strike
                strike_item = QTableWidgetItem(str(strike))
                strike_item.setTextAlignment(Qt.AlignCenter)
                strike_item.setFont(QFont("Arial", 11, QFont.Bold))
                self.eq_table.setItem(row, 2, strike_item)

                # قوة الإشارة (نجوم) - حفظها في العمود 1
                votes = int(strength.split('/')[0])
                star_item = QTableWidgetItem("⭐" * votes)
                star_item.setTextAlignment(Qt.AlignCenter)
                star_item.setForeground(QColor("lime") if consensus_dir == "Call" else QColor("red"))
                star_item.setFont(QFont("Arial", 12))
                self.eq_table.setItem(row, 1, star_item)

                # CALL / PUT RECOM
                if consensus_dir == "Call" and row < 6:
                    call_item = QTableWidgetItem("OPEN CALL")
                    call_item.setFont(QFont("Arial", 16, QFont.Bold))
                    call_item.setForeground(QColor("lime"))
                    call_item.setTextAlignment(Qt.AlignCenter)
                    self.eq_table.setItem(row, 0, call_item)
                elif consensus_dir == "Put" and row >= 6:
                    put_item = QTableWidgetItem("OPEN PUT")
                    put_item.setFont(QFont("Arial", 16, QFont.Bold))
                    put_item.setForeground(QColor("red"))
                    put_item.setTextAlignment(Qt.AlignCenter)
                    self.eq_table.setItem(row, 3, put_item)

                # SLP_t
                slp_idx = next((j for j in range(N_STRIKES) if strikes[j] == strike), 0)
                slp_item = QTableWidgetItem(f"{slp_values[slp_idx]:.2f}")
                slp_item.setTextAlignment(Qt.AlignCenter)
                slp_item.setForeground(QColor("lime") if slp_values[slp_idx] > 0 else QColor("red"))
                self.eq_table.setItem(row, 4, slp_item)

                # نسبة اتجاهي محلية (العمود 5)
                dir_bar_local = "█" * int(abs(dir_percentage_local) // 10) + "░" * (10 - int(abs(dir_percentage_local) // 10))
                dir_text_local = QTableWidgetItem(f"{dir_bar_local} {abs(dir_percentage_local):.0f}% {'↑' if dir_percentage_local > 0 else '↓'}")
                dir_text_local.setTextAlignment(Qt.AlignCenter)
                dir_text_local.setForeground(QColor("lime") if dir_percentage_local > 0 else QColor("red"))
                self.eq_table.setItem(row, 5, dir_text_local)

                # نسبة مخاطر محلية (العمود 6)
                risk_bar_local = "█" * int(abs(risk_percentage_local) // 10) + "░" * (10 - int(abs(risk_percentage_local) // 10))
                risk_text_local = QTableWidgetItem(f"{risk_bar_local} {abs(risk_percentage_local):.0f}% ⚠️")
                risk_text_local.setTextAlignment(Qt.AlignCenter)
                risk_text_local.setForeground(QColor("green") if risk_percentage_local > 0 else QColor("orange"))
                self.eq_table.setItem(row, 6, risk_text_local)

                row += 1
                self.data = results  # هذا السطر يملأ self.data بالنتائج للحفظ اللاحق
            # تنبيهات صوتية
            if sound_enabled:
                winsound.Beep(1000, 200)
                if any(abs(f) > 100000 for f in self.net_flow_values):
                    winsound.Beep(2000, 300)
                if any("13/14" in s or "14/14" in s for _, _, _, s, _, _ in self.strike_recommendations):
                    winsound.Beep(1500, 500)
                if any(abs(slp) > 1.0 for slp in slp_values):  # تنبيه لـ SLP_t
                    winsound.Beep(1200, 400)

            self.status_bar.showMessage(
                f"تم التحليل | Net GEX: {call_gex_total + put_gex_total:,.0f} | "
                f"Flip: {flip_str} | IV Skew: {iv_skew:.1%} | Tail: {tail_risk:.0f} | VWGF: قوي | SLP_t: متوسط {sum(slp_values)/len(slp_values):.2f}"
            )
            logging.info("تم التحليل بنجاح مع SLP_t")
            # === حفظ فوري بعد التحليل ===
            self.save_all_data()
        except Exception as e:
            self.status_bar.showMessage(f"خطأ: {str(e)}")
            logging.error(f"خطأ: {str(e)}", exc_info=True)

if __name__ == '__main__':
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)
    window = SPXTradingApp()
    window.show()
    with loop:
        loop.run_forever()