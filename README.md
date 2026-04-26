# THE SOVEREIGN SECRET MANAGER (VERITAS Ω)
### Secure Vault with Multi-Anchor Hardware Redundancy

The Sovereign Secret Manager is a high-security cryptographic vault designed to eliminate hardware lock-in. Built for power users and developers, it allows for multiple hardware keys (YubiKeys) to act as independent anchors for a single encrypted store.

## 🔱 Key Features
*   **Key-Wrapping Architecture**: Decouples the master encryption key from any single hardware device.
*   **Multi-Anchor Redundancy**: Bind multiple YubiKeys (Primary, Backup, Off-site) during setup. Any single key can unlock the vault.
*   **Argon2ID KDF**: Industry-standard memory-hard key derivation to protect against brute-force attacks.
*   **AES-256-GCM Encryption**: Authenticated encryption ensuring both confidentiality and data integrity.
*   **Unified Challenge Protocol**: Deterministic hardware handshake for high reliability.

## 🛠️ Requirements
*   Python 3.10+
*   PySide6 (for the GUI)
*   YubiKey Manager (ykman) CLI
*   One or more YubiKeys (HMAC-SHA1 slot 2 configured)

## 🔒 Security Posture
This repository follows the **Zero Leakage Protocol**. Encrypted volumes, salts, and hardware anchor metadata are strictly excluded via `.gitignore` and never touch the remote repository.

## 🚀 Quick Start
1.  Ensure `ykman` is in your PATH.
2.  Configure Slot 2 on your YubiKey: `ykman otp chalresp -g 2`.
3.  Run the manager: `python veritas_cipher_vault.py`.
4.  Bind your keys and finalize your sovereign setup.

---
*A VERITAS Ω Production*
