"""
reactive_wireframe_2d_circle.py

A PyQt5 widget that displays a 2D “donut‑node” wireframe network whose
nodes move and bounce inside a circle, and which expands/contracts
based on an audio “level” (e.g. your AI TTS amplitude). 
Call `orb.setLevel(v)` with v in [0.0,1.0] to pulse.
"""

import sys
import numpy as np
from PyQt5.QtWidgets import QApplication, QWidget
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QPen, QColor

class ReactiveWireframe2DCircle(QWidget):
    def __init__(self,
                    n_nodes=50,
                    threshold=0.6,
                    fps=30,
                    diameter=600,
                    max_pulse=0.4,
                    damping=0.2,
                    x=None,
                    y=None):
        super().__init__()
        self.setFixedSize(diameter, diameter)
        
        self.setWindowFlags(Qt.FramelessWindowHint |    
                            Qt.WindowStaysOnTopHint | 
                            Qt.Tool)                    
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        self.setWindowFlags(
            Qt.FramelessWindowHint |
            Qt.WindowStaysOnTopHint |
            Qt.Tool
        )
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAutoFillBackground(False)

        # Node/edge parameters
        self.n_nodes = n_nodes
        self.threshold = threshold

        # Initialize positions uniformly inside the unit circle
        angles = np.random.uniform(0, 2*np.pi, n_nodes)
        radii  = np.sqrt(np.random.uniform(0, 1, n_nodes))
        self.positions = np.column_stack((radii * np.cos(angles),
                                          radii * np.sin(angles)))

        # Random velocities
        ang_vels = np.random.uniform(0, 2*np.pi, n_nodes)
        speeds   = np.random.uniform(0.002, 0.01, n_nodes)
        self.velocities = np.column_stack((np.cos(ang_vels), np.sin(ang_vels))) * speeds[:, None]

        # Audio‑reactive scaling
        self.level     = 0.0
        self.scale     = 1.0
        self.max_pulse = max_pulse
        self.damping   = damping

        # Colors / sizes
        self.bg_color   = QColor(0, 0, 0)
        self.edge_color = QColor(255, 255, 255)
        self.node_color = QColor(255, 255, 255)
        self.node_radius = 3

        # Timer for animation
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._on_timer)
        self.timer.start(int(1000 / fps))

        # Position if specified
        if x is not None and y is not None:
            self.move(x, y)

    def setLevel(self, lvl: float):
        """Clamp and set audio level in [0.0, 1.0]."""
        self.level = max(0.0, min(1.0, lvl))

    def _on_timer(self):
        # Smoothly interpolate scale toward target
        target = 1.0 + self.level * self.max_pulse
        self.scale += (target - self.scale) * self.damping

        # Move nodes
        self.positions += self.velocities

        # Bounce inside unit circle
        for i, pos in enumerate(self.positions):
            r = np.linalg.norm(pos)
            if r > 1.0:
                # project outward normal
                normal = pos / r
                # reflect velocity: v' = v - 2 (v·n) n
                v = self.velocities[i]
                self.velocities[i] = v - 2 * np.dot(v, normal) * normal
                # push back inside
                self.positions[i] = normal * 1.0

        # Trigger repaint
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        # Compute display positions
        w, h = self.width(), self.height()
        center = np.array([w/2, h/2])
        # Scale normalized positions by radius*0.9 and audio scale
        disp = self.positions * (w/2 * 0.9) * self.scale + center

        # Draw edges
        pen = QPen(self.edge_color)
        pen.setWidth(1)
        painter.setPen(pen)
        for i in range(self.n_nodes):
            xi, yi = disp[i]
            for j in range(i+1, self.n_nodes):
                xj, yj = disp[j]
                # Use unscaled positions for threshold test in unit circle coords
                if np.linalg.norm(self.positions[i] - self.positions[j]) < self.threshold:
                    alpha = int(255 * (1 - np.linalg.norm(self.positions[i] - self.positions[j]) / self.threshold))
                    color = QColor(255, 255, 255, alpha)
                    pen.setColor(color)
                    painter.setPen(pen)
                    painter.drawLine(int(xi), int(yi), int(xj), int(yj))

        # Draw nodes (hollow circles)
        pen = QPen(self.node_color)
        pen.setWidth(2)
        painter.setPen(pen)
        for x, y in disp:
            painter.drawEllipse(int(x - self.node_radius), int(y - self.node_radius),
                                self.node_radius*2, self.node_radius*2)

        painter.end()

if __name__ == "__main__":
    app = QApplication(sys.argv)

    orb = ReactiveWireframe2DCircle(
        n_nodes=50,
        threshold=0.6,
        fps=30,
        diameter=300,     # smaller widget size
        max_pulse=0.5,
        damping=0.2
    )
    orb.show()

    # Move to middle bottom of the screen
    screen = app.primaryScreen().geometry()
    x = (screen.width() - orb.width()) // 2
    y = screen.height() - orb.height() - 40  # 40px margin from bottom
    orb.move(x, y)

    # Demo: simulate AI speech levels
    import random
    def speak():
        orb.setLevel(random.uniform(0.3, 1.0))
    def quiet():
        orb.setLevel(0.0)

    demo_timer = QTimer()
    demo_timer.timeout.connect(speak)
    demo_timer.start(200)  # random level every 200 ms
    QTimer.singleShot(6000, lambda: (demo_timer.stop(), quiet()))

    sys.exit(app.exec_())
