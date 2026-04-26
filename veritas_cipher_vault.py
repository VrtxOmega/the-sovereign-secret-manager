"""
VERITAS Ω CIPHER VAULT — SOVEREIGN EDITION
Secure secret manager with Multi-Hardware Redundancy (Unified Challenge Protocol)
Hardware Engine: ykman CLI (Primary) / yubikit HID (Fallback)
"""

import sys
import os
import json
import base64
import hashlib
import time
import secrets
import subprocess
from pathlib import Path
from typing import Optional, List

# GUI
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QListWidget, 
    QStackedWidget, QFrame, QMessageBox, QDialog
)
from PySide6.QtCore import Qt, Signal, QThread
from PySide6.QtGui import QColor, QFont, QPalette, QIcon

# Cryptography
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.backends import default_backend

try:
    from argon2.low_level import hash_secret_raw, Type
    ARGON2_AVAILABLE = True
except ImportError:
    ARGON2_AVAILABLE = False

# --- CONFIGURATION ---
VAULT_ROOT = Path(r"C:\Veritas_Lab\Vault_Sovereign")
VAULT_DATA = VAULT_ROOT / "data"
VAULT_CONFIG = VAULT_ROOT / "config.json"
VAULT_DATA.mkdir(parents=True, exist_ok=True)

# THE UNIFIED CHALLENGE - MUST BE IDENTICAL FOR BINDING AND UNLOCKING
VAULT_CHALLENGE = b"veritas-sovereign-anchor-v1"

# --- THEME ---
OBSIDIAN = "#050505"
GOLD = "#C9A84C"
SLATE = "#1A1A1A"

# --- CORE ENGINES ---

class YubiKeyEngine:
    @staticmethod
    def get_hmac_response(challenge: bytes, status_callback=None) -> Optional[bytes]:
        """Calculates HMAC-SHA1 using ykman CLI (Primary) or yubikit (Fallback)."""
        try:
            # TIER 1: ykman CLI
            if status_callback: status_callback("TOUCH YUBIKEY NOW")
            try:
                hex_chal = challenge.hex()
                res = subprocess.run(["ykman", "otp", "calculate", "2", hex_chal], 
                                   capture_output=True, text=True, check=True, timeout=15)
                return bytes.fromhex(res.stdout.strip())
            except subprocess.CalledProcessError as e:
                print(f"\n[!] HARDWARE ERROR: ykman failed (Code {e.returncode})")
                print(f"    Error Detail: {e.stderr.strip()}")
                return None
            except Exception as e:
                print(f"DIAGNOSTIC: CLI attempt failed: {e}")

            # TIER 2: Native Library Fallback
            from ykman.device import list_all_devices
            from yubikit.core.otp import OtpConnection
            from yubikit.yubiotp import YubiOtpSession
            
            devices = list_all_devices()
            for device, _ in devices:
                try:
                    with device.open_connection(OtpConnection) as conn:
                        session = YubiOtpSession(conn)
                        return session.calculate_hmac_sha1(2, challenge)
                except:
                    continue
            return None
        except Exception as e:
            print(f"DIAGNOSTIC: Hardware engine failed: {e}")
            return None

class VaultEngine:
    def __init__(self):
        self.master_key = None
        self.config = None

    def _derive_wrapping_key(self, passphrase: str, salt: bytes, hw_response: bytes) -> bytes:
        if ARGON2_AVAILABLE:
            argon_hash = hash_secret_raw(
                passphrase.encode(), salt, time_cost=3, memory_cost=256*1024, parallelism=4, hash_len=32, type=Type.ID
            )
        else:
            argon_hash = hashlib.pbkdf2_hmac('sha256', passphrase.encode(), salt, 100000)
            
        hkdf = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=b"veritas-vault-wrap", backend=default_backend())
        return hkdf.derive(argon_hash + hw_response)

    def initialize(self, passphrase: str, hmac_list: list) -> bool:
        salt = secrets.token_bytes(32)
        root_key = secrets.token_bytes(32)
        
        # Wrap the root_key for each hardware anchor
        wrapped_anchors = []
        for hmac in hmac_list:
            wrapping_key = self._derive_wrapping_key(passphrase, salt, hmac)
            aes = AESGCM(wrapping_key)
            nonce = secrets.token_bytes(12)
            wrapped = aes.encrypt(nonce, root_key, b"veritas-wrap-aad")
            wrapped_anchors.append({
                "hmac_anchor": base64.b64encode(hmac).decode(),
                "wrapped_key": base64.b64encode(wrapped).decode(),
                "nonce": base64.b64encode(nonce).decode()
            })
            
        # Canary uses the root_key for verification
        aes_root = AESGCM(root_key)
        canary_nonce = secrets.token_bytes(12)
        canary = aes_root.encrypt(canary_nonce, "Ω-VERIFIED-ORACLE-PASS".encode("utf-8"), b"veritas-aad")
        
        self.config = {
            "salt": base64.b64encode(salt).decode(),
            "wrapped_anchors": wrapped_anchors,
            "canary": base64.b64encode(canary).decode(),
            "canary_nonce": base64.b64encode(canary_nonce).decode()
        }
        VAULT_CONFIG.write_text(json.dumps(self.config))
        return True

    def unlock(self, passphrase: str, hw_response: bytes) -> bool:
        if not VAULT_CONFIG.exists(): return False
        self.config = json.loads(VAULT_CONFIG.read_text())
        
        salt = base64.b64decode(self.config["salt"])
        canary_enc = base64.b64decode(self.config["canary"])
        canary_nonce = base64.b64decode(self.config["canary_nonce"])
        anchors = self.config["wrapped_anchors"]

        for anchor in anchors:
            hmac_anchor = base64.b64decode(anchor["hmac_anchor"])
            if hw_response == hmac_anchor:
                try:
                    wrapping_key = self._derive_wrapping_key(passphrase, salt, hw_response)
                    aes_wrap = AESGCM(wrapping_key)
                    nonce = base64.b64decode(anchor["nonce"])
                    wrapped_key = base64.b64decode(anchor["wrapped_key"])
                    
                    root_key = aes_wrap.decrypt(nonce, wrapped_key, b"veritas-wrap-aad")
                    
                    # Verify root_key with canary
                    aes_root = AESGCM(root_key)
                    if aes_root.decrypt(canary_nonce, canary_enc, b"veritas-aad") == "Ω-VERIFIED-ORACLE-PASS".encode("utf-8"):
                        self.master_key = root_key
                        return True
                except Exception as e:
                    print(f"DIAGNOSTIC: Anchor unwrap failed: {e}")
                    continue
        return False

    def encrypt(self, data: str) -> str:
        aes = AESGCM(self.master_key)
        nonce = os.urandom(12)
        ciphertext = aes.encrypt(nonce, data.encode(), b"veritas-aad")
        return base64.b64encode(nonce + ciphertext).decode()

    def decrypt(self, encrypted_data: str) -> Optional[str]:
        try:
            raw = base64.b64decode(encrypted_data)
            nonce, ciphertext = raw[:12], raw[12:]
            aes = AESGCM(self.master_key)
            return aes.decrypt(nonce, ciphertext, b"veritas-aad").decode()
        except: return None

    def ingest_backups(self) -> int:
        count = 0
        try:
            import sys
            sys.path.append(r"C:\Veritas_Lab")
            content = Path(r"C:\Veritas_Lab\backup_secrets.py").read_text()
            if "fallback_secrets = {" in content:
                import ast
                start = content.find("fallback_secrets = {")
                end = content.find("}", start) + 1
                dict_str = content[start:end].split("=", 1)[1].strip()
                fallback = ast.literal_eval(dict_str)
                for name, val in fallback.items():
                    target = VAULT_DATA / f"{name}.enc"
                    if not target.exists():
                        target.write_text(self.encrypt(val))
                        count += 1
        except Exception as e: print(f"DIAGNOSTIC: Script ingest failed: {e}")
        backup_dir = Path(r"C:\Veritas_Lab\secret_manager_backup")
        if backup_dir.exists():
            for f in backup_dir.glob("*.txt"):
                target = VAULT_DATA / f"{f.stem}.enc"
                if not target.exists():
                    target.write_text(self.encrypt(f.read_text().strip()))
                    count += 1
        return count

# --- UI COMPONENTS ---

class HardwareWorker(QThread):
    finished = Signal(object)
    status = Signal(str)
    def __init__(self, challenge):
        super().__init__()
        self.challenge = challenge
    def run(self):
        res = YubiKeyEngine.get_hmac_response(self.challenge, status_callback=self.status.emit)
        self.finished.emit(res)

class SovereignButton(QPushButton):
    def __init__(self, text, primary=True):
        super().__init__(text)
        self.setFixedHeight(45)
        self.setCursor(Qt.PointingHandCursor)
        color = GOLD if primary else SLATE
        text_color = OBSIDIAN if primary else GOLD
        self.setStyleSheet(f"QPushButton {{ background-color: {color}; color: {text_color}; border: 1px solid {GOLD}; border-radius: 4px; font-weight: bold; }} QPushButton:hover {{ background-color: #E0C16C; }}")

class SecretManager(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SOVEREIGN SECRET MANAGER")
        self.setWindowIcon(QIcon(r"C:\Veritas_Lab\sovereign_icon.ico"))
        self.setMinimumSize(1000, 700)
        self.engine = VaultEngine()
        self.hmac_list = []
        self.setup_ui()
        self.refresh_view()

    def setup_ui(self):
        self.setStyleSheet(f"background-color: {OBSIDIAN}; color: {GOLD}; font-family: 'Segoe UI';")
        self.stack = QStackedWidget()
        self.setCentralWidget(self.stack)

        # SETUP
        setup_page = QWidget()
        l = QVBoxLayout(setup_page); l.setAlignment(Qt.AlignCenter); l.setSpacing(20)
        l.addWidget(QLabel("Ω SOVEREIGN SECRET MANAGER: INITIALIZATION"), 0, Qt.AlignCenter)
        self.setup_pw = QLineEdit(); self.setup_pw.setEchoMode(QLineEdit.Password); self.setup_pw.setPlaceholderText("PASSPHRASE"); self.setup_pw.setFixedWidth(400)
        self.setup_pw_cf = QLineEdit(); self.setup_pw_cf.setEchoMode(QLineEdit.Password); self.setup_pw_cf.setPlaceholderText("CONFIRM"); self.setup_pw_cf.setFixedWidth(400)
        self.bind_btn = SovereignButton("BIND YUBIKEY", False); self.bind_btn.setFixedWidth(400)
        self.init_btn = SovereignButton("FINALIZE SETUP"); self.init_btn.setFixedWidth(400)
        self.bind_btn.clicked.connect(self.on_bind_clicked)
        self.init_btn.clicked.connect(self.on_init_clicked)
        l.addWidget(self.setup_pw); l.addWidget(self.setup_pw_cf); l.addWidget(self.bind_btn); l.addWidget(self.init_btn)
        self.stack.addWidget(setup_page)

        # UNLOCK
        unlock_page = QWidget()
        lu = QVBoxLayout(unlock_page); lu.setAlignment(Qt.AlignCenter); lu.setSpacing(20)
        lu.addWidget(QLabel("SOVEREIGN SECRET MANAGER"), 0, Qt.AlignCenter)
        self.unlock_pw = QLineEdit(); self.unlock_pw.setEchoMode(QLineEdit.Password); self.unlock_pw.setPlaceholderText("MASTER PASSPHRASE"); self.unlock_pw.setFixedWidth(400)
        self.unlock_btn = SovereignButton("UNLOCK VAULT"); self.unlock_btn.setFixedWidth(400)
        self.unlock_btn.clicked.connect(self.on_unlock_clicked)
        lu.addWidget(self.unlock_pw); lu.addWidget(self.unlock_btn)
        self.stack.addWidget(unlock_page)

        # MAIN
        vault_page = QWidget()
        lv = QHBoxLayout(vault_page); lv.setContentsMargins(0,0,0,0)
        sidebar = QFrame(); sidebar.setFixedWidth(300); sidebar.setStyleSheet(f"background-color: {SLATE};")
        ls = QVBoxLayout(sidebar)
        self.list = QListWidget(); self.list.itemSelectionChanged.connect(self.on_select)
        self.add_btn = SovereignButton("[+] NEW"); self.del_btn = SovereignButton("[-] DELETE", False)
        self.ingest_btn = SovereignButton("INGEST BACKUPS", False)
        self.ingest_btn.clicked.connect(self.on_ingest)
        ls.addWidget(QLabel("Ω VOLUMES")); ls.addWidget(self.list); ls.addWidget(self.add_btn); ls.addWidget(self.del_btn); ls.addWidget(self.ingest_btn)
        
        editor_pane = QWidget(); le = QVBoxLayout(editor_pane)
        
        # --- WATERMARK STACK ---
        watermark_stack = QWidget()
        stack_layout = QGridLayout(watermark_stack)
        stack_layout.setContentsMargins(0,0,0,0)
        
        self.watermark = QLabel("Ω")
        self.watermark.setAlignment(Qt.AlignCenter)
        self.watermark.setStyleSheet(f"color: rgba(201, 168, 76, 40); font-family: 'Georgia'; font-size: 350px;")
        
        self.editor = QTextEdit()
        self.editor.setStyleSheet("background: transparent; border: none; font-size: 14px; color: #EEE;")
        
        stack_layout.addWidget(self.watermark, 0, 0)
        stack_layout.addWidget(self.editor, 0, 0)
        # -----------------------

        self.save_btn = SovereignButton("SAVE SECURELY")
        self.save_btn.clicked.connect(self.on_save)
        self.add_btn.clicked.connect(self.on_new)
        self.del_btn.clicked.connect(self.on_del)
        le.addWidget(watermark_stack); le.addWidget(self.save_btn)
        
        lv.addWidget(sidebar); lv.addWidget(editor_pane)
        self.stack.addWidget(vault_page)

    def refresh_view(self):
        if not VAULT_CONFIG.exists(): self.stack.setCurrentIndex(0)
        elif not self.engine.master_key: self.stack.setCurrentIndex(1)
        else:
            self.stack.setCurrentIndex(2)
            self.list.clear()
            for f in VAULT_DATA.glob("*.enc"): self.list.addItem(f.stem)

    def on_bind_clicked(self):
        self.bind_btn.setEnabled(False); self.bind_btn.setText("POLLING...")
        self.worker = HardwareWorker(VAULT_CHALLENGE)
        self.worker.status.connect(lambda m: self.bind_btn.setText(m))
        self.worker.finished.connect(self.on_bind_done)
        self.worker.start()

    def on_bind_done(self, hmac):
        self.bind_btn.setEnabled(True)
        if hmac:
            self.hmac_list.append(hmac)
            self.bind_btn.setText(f"BOUND [{len(self.hmac_list)} KEYS]")
            QMessageBox.information(self, "Success", f"Key #{len(self.hmac_list)} bound. Click again to add backup key, or Finalize.")
        else: self.bind_btn.setText("BIND YUBIKEY")

    def on_init_clicked(self):
        pw = self.setup_pw.text()
        if pw != self.setup_pw_cf.text() or len(pw) < 8 or not self.hmac_list:
            QMessageBox.warning(self, "Error", "Invalid setup parameters.")
            return
        if self.engine.initialize(pw, self.hmac_list):
            QMessageBox.information(self, "Success", "Vault Initialized.")
            self.refresh_view()

    def on_unlock_clicked(self):
        pw = self.unlock_pw.text()
        if not pw: return
        self.unlock_btn.setEnabled(False); self.unlock_btn.setText("POLLING...")
        self.unlock_worker = HardwareWorker(VAULT_CHALLENGE)
        self.unlock_worker.status.connect(lambda m: self.unlock_btn.setText(m))
        self.unlock_worker.finished.connect(lambda h: self.on_unlock_done(pw, h))
        self.unlock_worker.start()

    def on_unlock_done(self, pw, hmac):
        self.unlock_btn.setEnabled(True); self.unlock_btn.setText("UNLOCK VAULT")
        if hmac and self.engine.unlock(pw, hmac): self.refresh_view()
        else: QMessageBox.critical(self, "Denied", "Hardware mismatch or wrong passphrase.")

    def on_select(self):
        items = self.list.selectedItems()
        if items:
            path = VAULT_DATA / f"{items[0].text()}.enc"
            dec = self.engine.decrypt(path.read_text())
            self.editor.setPlainText(dec or "DECRYPTION FAILED")

    def on_save(self):
        items = self.list.selectedItems()
        if items:
            path = VAULT_DATA / f"{items[0].text()}.enc"
            path.write_text(self.engine.encrypt(self.editor.toPlainText()))
            QMessageBox.information(self, "Saved", "Secret updated.")

    def on_new(self):
        name = f"SECRET_{int(time.time())}"
        (VAULT_DATA / f"{name}.enc").write_text(self.engine.encrypt("New Secret Content"))
        self.refresh_view()

    def on_del(self):
        items = self.list.selectedItems()
        if items:
            (VAULT_DATA / f"{items[0].text()}.enc").unlink()
            self.editor.clear(); self.refresh_view()

    def on_ingest(self):
        count = self.engine.ingest_backups()
        QMessageBox.information(self, "Ingest Complete", f"Imported {count} secrets from legacy backups.")
        self.refresh_view()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SecretManager()
    window.show()
    sys.exit(app.exec())
