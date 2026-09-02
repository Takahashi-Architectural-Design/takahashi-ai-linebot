import os

bind = f"0.0.0.0:{os.environ.get('PORT', '5000')}"
# AI応答を待つ間に他ユーザーのwebhookを詰まらせないようスレッドで捌く
workers = 1
threads = 8
# Claude の応答待ちでワーカーを殺されないように既定の30秒から延長
timeout = 120
