#!/bin/bash
# ============================================
# 智语AI客服系统 - 数据库自动备份脚本
# 运行在云服务器上，定时导出数据库并推送到 GitHub
# ============================================

set -e

BACKUP_REPO_DIR="/opt/ai-kefu/backup-repo"
APP_DIR="/opt/ai-kefu"
DATE=$(date +%Y%m%d_%H%M%S)
LOG_FILE="/opt/ai-kefu/backup.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "===== 开始数据库备份 ====="

# 确保备份仓库目录存在
if [ ! -d "$BACKUP_REPO_DIR/.git" ]; then
    log "错误: 备份仓库未初始化，请先运行 setup 脚本"
    exit 1
fi

cd "$APP_DIR"

# dumpdata 公共参数（--skip-checks 跳过 admin 配置检查）
DUMP_CMD="python manage.py dumpdata --indent 2 --skip-checks"

# 1. 导出完整数据库
log "导出完整数据库..."
docker compose exec -T backend $DUMP_CMD \
    --exclude auth.permission \
    --exclude contenttypes \
    > "$BACKUP_REPO_DIR/backups/full_backup_${DATE}.json" 2>>"$LOG_FILE"

# 2. 分模块导出关键数据
log "导出知识库数据..."
docker compose exec -T backend $DUMP_CMD knowledge \
    > "$BACKUP_REPO_DIR/backups/knowledge_${DATE}.json" 2>>"$LOG_FILE"

log "导出商品数据..."
docker compose exec -T backend $DUMP_CMD products \
    > "$BACKUP_REPO_DIR/backups/products_${DATE}.json" 2>>"$LOG_FILE"

log "导出店铺数据..."
docker compose exec -T backend $DUMP_CMD shops \
    > "$BACKUP_REPO_DIR/backups/shops_${DATE}.json" 2>>"$LOG_FILE"

log "导出用户数据..."
docker compose exec -T backend $DUMP_CMD accounts \
    > "$BACKUP_REPO_DIR/backups/accounts_${DATE}.json" 2>>"$LOG_FILE"

log "导出聊天记录..."
docker compose exec -T backend $DUMP_CMD chat \
    > "$BACKUP_REPO_DIR/backups/chat_${DATE}.json" 2>>"$LOG_FILE"

log "导出学习数据..."
docker compose exec -T backend $DUMP_CMD learning \
    > "$BACKUP_REPO_DIR/backups/learning_${DATE}.json" 2>>"$LOG_FILE"

log "导出快捷回复..."
docker compose exec -T backend $DUMP_CMD quick_replies \
    > "$BACKUP_REPO_DIR/backups/quick_replies_${DATE}.json" 2>>"$LOG_FILE"

log "导出AI配置..."
docker compose exec -T backend $DUMP_CMD ai \
    > "$BACKUP_REPO_DIR/backups/ai_${DATE}.json" 2>>"$LOG_FILE"

# 3. 清理7天前的旧备份（只保留最近7天）
log "清理90天前的旧备份..."
find "$BACKUP_REPO_DIR/backups/" -name "*.json" -mtime +90 -delete 2>>"$LOG_FILE"

# 4. 提交并推送到 GitHub
cd "$BACKUP_REPO_DIR"
git add backups/
git add -u backups/  # 处理被删除的旧文件

# 检查是否有变更
if git diff --cached --quiet; then
    log "数据无变化，跳过提交"
else
    git commit -m "自动备份: ${DATE}"
    git push origin main
    log "备份已推送到 GitHub"
fi

log "===== 备份完成 ====="
