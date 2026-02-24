#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
向服务器 .env 文件添加 Doubao 和 Qwen API 密钥
"""

import paramiko
import sys

# 服务器配置
SERVER_HOST = "120.26.199.225"
SERVER_USER = "root"
SERVER_PASSWORD = "Sunhao2007!!"
SERVER_PORT = 22

# API 密钥
DOUBAO_API_KEY = "d26a35bc-c3a5-43ae-a18a-03c91ba62c9e"
QWEN_API_KEY = "sk-e6e8a33e689f44228fedb83985e070b0"

def main():
    print("连接服务器...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    
    try:
        ssh.connect(SERVER_HOST, port=SERVER_PORT, username=SERVER_USER, password=SERVER_PASSWORD, timeout=60)
        print("连接成功！")
        
        # 检查当前 .env 文件
        print("\n检查当前 .env 文件中的 API 配置...")
        stdin, stdout, stderr = ssh.exec_command("cat /opt/ai-kefu/.env | grep -E 'DOUBAO|QWEN' || echo '未找到配置'")
        current_config = stdout.read().decode('utf-8').strip()
        print(f"当前配置: {current_config}")
        
        # 添加 DOUBAO_API_KEY
        print("\n添加 DOUBAO_API_KEY...")
        cmd = f"grep -q 'DOUBAO_API_KEY' /opt/ai-kefu/.env && sed -i 's/^DOUBAO_API_KEY=.*/DOUBAO_API_KEY={DOUBAO_API_KEY}/' /opt/ai-kefu/.env || echo 'DOUBAO_API_KEY={DOUBAO_API_KEY}' >> /opt/ai-kefu/.env"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        err = stderr.read().decode('utf-8')
        if err:
            print(f"错误: {err}")
        else:
            print("DOUBAO_API_KEY 添加成功！")
        
        # 添加 QWEN_API_KEY
        print("\n添加 QWEN_API_KEY...")
        cmd = f"grep -q 'QWEN_API_KEY' /opt/ai-kefu/.env && sed -i 's/^QWEN_API_KEY=.*/QWEN_API_KEY={QWEN_API_KEY}/' /opt/ai-kefu/.env || echo 'QWEN_API_KEY={QWEN_API_KEY}' >> /opt/ai-kefu/.env"
        stdin, stdout, stderr = ssh.exec_command(cmd)
        err = stderr.read().decode('utf-8')
        if err:
            print(f"错误: {err}")
        else:
            print("QWEN_API_KEY 添加成功！")
        
        # 验证配置
        print("\n验证配置...")
        stdin, stdout, stderr = ssh.exec_command("cat /opt/ai-kefu/.env | grep -E 'DOUBAO|QWEN'")
        new_config = stdout.read().decode('utf-8').strip()
        print(f"新配置:\n{new_config}")
        
        # 重启后端服务
        print("\n重启后端服务...")
        stdin, stdout, stderr = ssh.exec_command("cd /opt/ai-kefu && docker compose restart backend")
        output = stdout.read().decode('utf-8')
        err = stderr.read().decode('utf-8')
        print(f"输出: {output}")
        if err:
            print(f"信息: {err}")
        
        # 等待服务启动并检查状态
        print("\n等待服务启动...")
        import time
        time.sleep(5)
        
        stdin, stdout, stderr = ssh.exec_command("cd /opt/ai-kefu && docker compose ps backend")
        status = stdout.read().decode('utf-8')
        print(f"后端服务状态:\n{status}")
        
        print("\n配置完成！Doubao 和 Qwen API 现在可以使用了。")
        
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
    finally:
        ssh.close()

if __name__ == "__main__":
    main()
