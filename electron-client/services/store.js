/**
 * Simple JSON file store (replaces electron-store)
 */
const fs = require('fs');
const path = require('path');
const { app } = require('electron');

class SimpleStore {
  constructor(opts = {}) {
    const userDataPath = app.getPath('userData');
    this.filePath = path.join(userDataPath, 'config.json');
    this.defaults = opts.defaults || {};
    this.data = { ...this.defaults };
    this._load();
  }

  _load() {
    try {
      if (fs.existsSync(this.filePath)) {
        const raw = fs.readFileSync(this.filePath, 'utf8');
        this.data = { ...this.defaults, ...JSON.parse(raw) };
      }
    } catch (e) {
      this.data = { ...this.defaults };
    }
  }

  _save() {
    try {
      const dir = path.dirname(this.filePath);
      if (!fs.existsSync(dir)) fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(this.filePath, JSON.stringify(this.data, null, 2), 'utf8');
    } catch (e) {
      console.error('Store save error:', e);
    }
  }

  get(key) {
    return key ? this.data[key] : this.data;
  }

  set(key, value) {
    this.data[key] = value;
    this._save();
  }

  delete(key) {
    delete this.data[key];
    this._save();
  }
}

module.exports = SimpleStore;
