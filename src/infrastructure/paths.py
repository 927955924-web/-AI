import os


def project_root_dir():
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def app_data_dir(app_name="电商客服"):
    base = os.getenv("APPDATA") or os.path.expanduser("~")
    path = os.path.join(base, app_name)
    os.makedirs(path, exist_ok=True)
    return path


def app_db_path(app_name="电商客服"):
    return os.path.join(app_data_dir(app_name), "app.db")


def app_log_path(app_name="电商客服"):
    return os.path.join(app_data_dir(app_name), "app.log")

