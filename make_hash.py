"""สร้าง password_hash สำหรับใส่ใน secrets:  python make_hash.py"""
import getpass

from auth import make_hash

if __name__ == "__main__":
    pw = getpass.getpass("Password: ")
    print(make_hash(pw))
