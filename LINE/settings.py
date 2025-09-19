# 正しいsettings.pyの内容が必要です
# 現在の内容はviews.pyのものなので、元のsettings.pyを復元してください

# 追加すべき設定のみ：
LOGIN_URL = '/'
LOGIN_REDIRECT_URL = '/'
LOGOUT_REDIRECT_URL = '/'

# セキュリティ設定
SECURE_BROWSER_XSS_FILTER = True
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = 'DENY'