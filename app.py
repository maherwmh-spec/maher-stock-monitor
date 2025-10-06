# نظام مراقبة الأسهم السعودية - الإصدار الكامل
# يدعم استراتيجيتين: صقر التداول والفرصة السريعة
# مسح شامل للسوق + بحث فوري + تفاصيل كاملة

from flask import Flask, render_template, jsonify, request
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import json
import os

app = Flask(__name__)

# قائمة شاملة بجميع شركات السوق السعودي (143 شركة)
from saudi_market_stocks import SAUDI_MARKET_STOCKS

# مسار ملف الكاش
CACHE_FILE = 'market_scan_cache.json'
CACHE_DURATION = timedelta(hours=6)  # تحديث كل 6 ساعات

def get_yfinance_data(symbol, period="1y"):
    """جلب بيانات السهم من Yahoo Finance"""
    try:
        ticker = yf.Ticker(symbol)
        df = ticker.history(period=period)
        if df.empty:
            return pd.DataFrame()
        return df
    except Exception as e:
        print(f"[ERROR] Failed to fetch {symbol}: {e}")
        return pd.DataFrame()

def get_tasi_data():
    """جلب بيانات مؤشر تاسي"""
    return get_yfinance_data("^TASI.SR", period="1y")

def calculate_indicators(df):
    """حساب جميع المؤشرات الفنية"""
    if df.empty or len(df) < 200:
        return df
    
    # المتوسطات المتحركة
    df['MA20'] = df['Close'].rolling(window=20).mean()
    df['MA50'] = df['Close'].rolling(window=50).mean()
    df['MA100'] = df['Close'].rolling(window=100).mean()
    df['MA200'] = df['Close'].rolling(window=200).mean()
    
    # RSI
    delta = df['Close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['RSI'] = 100 - (100 / (1 + rs))
    
    # MACD
    exp1 = df['Close'].ewm(span=12, adjust=False).mean()
    exp2 = df['Close'].ewm(span=26, adjust=False).mean()
    df['MACD'] = exp1 - exp2
    df['Signal_Line'] = df['MACD'].ewm(span=9, adjust=False).mean()
    
    # Bollinger Bands
    df['BB_Middle'] = df['Close'].rolling(window=20).mean()
    bb_std = df['Close'].rolling(window=20).std()
    df['Upper_Band'] = df['BB_Middle'] + (bb_std * 2)
    df['Lower_Band'] = df['BB_Middle'] - (bb_std * 2)
    
    # OBV
    df['OBV'] = (np.sign(df['Close'].diff()) * df['Volume']).fillna(0).cumsum()
    
    # Volume Average
    df['Volume_MA20'] = df['Volume'].rolling(window=20).mean()
    
    return df

def analyze_hawk_strategy(stock_data, tasi_data, sector_trend=True):
    """
    استراتيجية صقر التداول (9 شروط)
    """
    if stock_data.empty or len(stock_data) < 200:
        return None
    
    latest = stock_data.iloc[-1]
    
    # الشروط التسعة
    conditions = {
        'tasi': bool(tasi_data["Close"].iloc[-1] > tasi_data["Close"].iloc[-5:].mean()),
        'sector': sector_trend,  # افتراضي إيجابي
        'obv': bool(latest["OBV"] > stock_data["OBV"].iloc[-20:].mean()),
        'volume': bool(latest["Volume"] > latest["Volume_MA20"] * 2),
        'breakout': bool(latest["Close"] > stock_data["High"].iloc[-11:-1].max()),
        'ma': bool(latest["Close"] > latest["MA50"]),
        'rsi': bool(50 < latest["RSI"] < 70),
        'macd': bool(latest["MACD"] > latest["Signal_Line"] and latest["MACD"] > 0),
        'bollinger': bool(latest["Close"] > latest["Upper_Band"])
    }
    
    conditions_met = sum(conditions.values())
    percentage = (conditions_met / 9) * 100
    
    return {
        'conditions': conditions,
        'conditions_met': conditions_met,
        'total_conditions': 9,
        'percentage': round(percentage, 1),
        'signal': 'buy' if conditions_met == 9 else ('promising' if conditions_met >= 7 else 'watch')
    }

def analyze_quick_strategy(stock_data, tasi_data):
    """
    استراتيجية الفرصة السريعة (8 شروط - أكثر مرونة)
    """
    if stock_data.empty or len(stock_data) < 200:
        return None
    
    latest = stock_data.iloc[-1]
    
    # الشروط الثمانية (بدون OBV)
    conditions = {
        'tasi': bool(tasi_data["Close"].iloc[-1] > tasi_data["Close"].iloc[-5:].mean()),
        'volume': bool(latest["Volume"] > latest["Volume_MA20"] * 1.5),  # أقل صرامة
        'breakout': bool(latest["Close"] > stock_data["High"].iloc[-11:-1].max()),
        'ma20': bool(latest["Close"] > latest["MA20"]),  # MA20 بدلاً من MA50
        'ma50': bool(latest["Close"] > latest["MA50"]),
        'rsi': bool(45 < latest["RSI"] < 75),  # نطاق أوسع
        'macd': bool(latest["MACD"] > latest["Signal_Line"]),  # بدون شرط الصفر
        'bollinger': bool(latest["Close"] > latest["BB_Middle"])  # الوسط بدلاً من الأعلى
    }
    
    conditions_met = sum(conditions.values())
    percentage = (conditions_met / 8) * 100
    
    return {
        'conditions': conditions,
        'conditions_met': conditions_met,
        'total_conditions': 8,
        'percentage': round(percentage, 1),
        'signal': 'buy' if conditions_met == 8 else ('promising' if conditions_met >= 6 else 'watch')
    }

def calculate_entry_exit_points(stock_data):
    """حساب نقاط الدخول والخروج"""
    if stock_data.empty:
        return None
    
    latest = stock_data.iloc[-1]
    current_price = latest["Close"]
    
    # سعر الدخول المقترح (السعر الحالي أو أقل قليلاً)
    entry_price = round(current_price * 0.995, 2)  # -0.5%
    
    # وقف الخسارة (-5%)
    stop_loss = round(current_price * 0.95, 2)
    
    # الهدف الأول (+10%)
    target1 = round(current_price * 1.10, 2)
    
    # الهدف الثاني (+20%)
    target2 = round(current_price * 1.20, 2)
    
    return {
        'current_price': round(current_price, 2),
        'entry_price': entry_price,
        'stop_loss': stop_loss,
        'target1': target1,
        'target2': target2,
        'risk_reward_1': round((target1 - entry_price) / (entry_price - stop_loss), 2),
        'risk_reward_2': round((target2 - entry_price) / (entry_price - stop_loss), 2)
    }

def get_all_indicators(stock_data):
    """جلب جميع المؤشرات للعرض"""
    if stock_data.empty:
        return None
    
    latest = stock_data.iloc[-1]
    
    return {
        'rsi': round(latest["RSI"], 2),
        'macd': round(latest["MACD"], 2),
        'signal_line': round(latest["Signal_Line"], 2),
        'ma20': round(latest["MA20"], 2),
        'ma50': round(latest["MA50"], 2),
        'ma100': round(latest["MA100"], 2),
        'ma200': round(latest["MA200"], 2),
        'upper_band': round(latest["Upper_Band"], 2),
        'middle_band': round(latest["BB_Middle"], 2),
        'lower_band': round(latest["Lower_Band"], 2),
        'obv': int(latest["OBV"]),
        'volume': int(latest["Volume"]),
        'volume_ma20': int(latest["Volume_MA20"])
    }

def analyze_single_stock(company_name, symbol, sector):
    """تحليل سهم واحد بالكامل"""
    print(f"[INFO] Analyzing {company_name} ({symbol})...")
    
    # جلب البيانات
    yf_symbol = f"{symbol}.SR"
    stock_data = get_yfinance_data(yf_symbol)
    
    if stock_data.empty:
        return None
    
    # حساب المؤشرات
    stock_data = calculate_indicators(stock_data)
    
    # جلب بيانات تاسي
    tasi_data = get_tasi_data()
    if tasi_data.empty:
        return None
    
    # تحليل الاستراتيجيتين
    hawk_analysis = analyze_hawk_strategy(stock_data, tasi_data)
    quick_analysis = analyze_quick_strategy(stock_data, tasi_data)
    
    if not hawk_analysis or not quick_analysis:
        return None
    
    # حساب نقاط الدخول والخروج
    entry_exit = calculate_entry_exit_points(stock_data)
    
    # جلب جميع المؤشرات
    indicators = get_all_indicators(stock_data)
    
    return {
        'company': company_name,
        'symbol': symbol,
        'sector': sector,
        'hawk': hawk_analysis,
        'quick': quick_analysis,
        'entry_exit': entry_exit,
        'indicators': indicators,
        'timestamp': datetime.now().isoformat()
    }

def scan_market():
    """مسح السوق بالكامل (143 شركة)"""
    print("[INFO] Starting full market scan...")
    results = []
    
    for company_name, data in SAUDI_MARKET_STOCKS.items():
        symbol = data['symbol']
        sector = data['sector']
        
        analysis = analyze_single_stock(company_name, symbol, sector)
        if analysis:
            results.append(analysis)
    
    print(f"[INFO] Market scan completed. {len(results)} stocks analyzed.")
    return results

def load_cache():
    """تحميل البيانات المحفوظة"""
    if not os.path.exists(CACHE_FILE):
        return None
    
    try:
        with open(CACHE_FILE, 'r', encoding='utf-8') as f:
            cache = json.load(f)
        
        # التحقق من صلاحية الكاش
        cache_time = datetime.fromisoformat(cache['timestamp'])
        if datetime.now() - cache_time < CACHE_DURATION:
            print("[INFO] Using cached data")
            return cache['data']
        else:
            print("[INFO] Cache expired")
            return None
    except Exception as e:
        print(f"[ERROR] Failed to load cache: {e}")
        return None

def save_cache(data):
    """حفظ البيانات"""
    try:
        cache = {
            'timestamp': datetime.now().isoformat(),
            'data': data
        }
        with open(CACHE_FILE, 'w', encoding='utf-8') as f:
            json.dump(cache, f, ensure_ascii=False, indent=2)
        print("[INFO] Cache saved")
    except Exception as e:
        print(f"[ERROR] Failed to save cache: {e}")

@app.route('/')
def index():
    """الصفحة الرئيسية"""
    return render_template('index.html')

@app.route('/api/market-scan')
def api_market_scan():
    """API: مسح السوق (يستخدم الكاش إن وجد)"""
    # محاولة تحميل من الكاش
    data = load_cache()
    
    if data is None:
        # مسح جديد
        data = scan_market()
        save_cache(data)
    
    # ترتيب النتائج
    hawk_top = sorted([d for d in data if d['hawk']], 
                     key=lambda x: x['hawk']['percentage'], reverse=True)[:20]
    quick_top = sorted([d for d in data if d['quick']], 
                      key=lambda x: x['quick']['percentage'], reverse=True)[:20]
    
    # إحصائيات
    tasi_data = get_tasi_data()
    tasi_current = round(tasi_data["Close"].iloc[-1], 2) if not tasi_data.empty else 0
    tasi_change = round(((tasi_data["Close"].iloc[-1] / tasi_data["Close"].iloc[-2]) - 1) * 100, 2) if not tasi_data.empty else 0
    
    hawk_signals = len([d for d in data if d['hawk']['signal'] == 'buy'])
    quick_signals = len([d for d in data if d['quick']['signal'] == 'buy'])
    
    return jsonify({
        'success': True,
        'timestamp': datetime.now().isoformat(),
        'stats': {
            'total_stocks': len(data),
            'tasi_current': tasi_current,
            'tasi_change': tasi_change,
            'hawk_signals': hawk_signals,
            'quick_signals': quick_signals
        },
        'hawk_top20': hawk_top,
        'quick_top20': quick_top
    })

@app.route('/api/search')
def api_search():
    """API: بحث عن سهم محدد"""
    query = request.args.get('q', '').strip()
    
    if not query:
        return jsonify({'success': False, 'error': 'No query provided'})
    
    # البحث في القائمة
    found = None
    for company_name, data in SAUDI_MARKET_STOCKS.items():
        if query.lower() in company_name.lower() or query == data['symbol']:
            found = (company_name, data['symbol'], data['sector'])
            break
    
    if not found:
        return jsonify({'success': False, 'error': 'Stock not found'})
    
    # تحليل السهم
    analysis = analyze_single_stock(found[0], found[1], found[2])
    
    if not analysis:
        return jsonify({'success': False, 'error': 'Failed to analyze stock'})
    
    return jsonify({'success': True, 'data': analysis})

@app.route('/api/refresh')
def api_refresh():
    """API: مسح جديد للسوق (تجاهل الكاش)"""
    data = scan_market()
    save_cache(data)
    
    return jsonify({'success': True, 'message': 'Market scan completed', 'total': len(data)})

if __name__ == '__main__':
    # إنشاء مجلد templates إن لم يكن موجوداً
    os.makedirs('templates', exist_ok=True)
    
    app.run(host='0.0.0.0', port=5000, debug=False)
