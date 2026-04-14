from flask import Flask, render_template, request, session, redirect, url_for, jsonify
import sqlite3
import hashlib

app = Flask(__name__)
app.secret_key = 'your_secret_key_here_change_this'

def get_db():
    conn = sqlite3.connect('gameshop.db')
    conn.row_factory = sqlite3.Row
    return conn

def hash_password(password):
    return hashlib.sha256(password.encode()).hexdigest()

def get_cart_count(user_id):
    db = get_db()
    cursor = db.cursor()
    cursor.execute('''SELECT SUM(quantity) as count
                      FROM cart_items ci
                      JOIN cart c ON ci.cart_id = c.cart_id
                      WHERE c.user_id = ?''', (user_id,))
    result = cursor.fetchone()
    db.close()
    return result['count'] or 0

# ===== AUTH =====
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        email = request.form.get('email', '').strip()
        password = request.form.get('password', '')
        confirm_password = request.form.get('confirm_password', '')
        
        if not username or not email or not password:
            return render_template('register.html', error='กรุณากรอกข้อมูลให้ครบ')
        if password != confirm_password:
            return render_template('register.html', error='รหัสผ่านไม่ตรงกัน')
        if len(password) < 6:
            return render_template('register.html', error='รหัสผ่านต้องมีอย่างน้อย 6 ตัวอักษร')
        
        db = get_db()
        cursor = db.cursor()
        try:
            cursor.execute('INSERT INTO users (username, email, password) VALUES (?, ?, ?)',
                          (username, email, hash_password(password)))
            user_id = cursor.lastrowid
            cursor.execute('INSERT INTO cart (user_id) VALUES (?)', (user_id,))
            db.commit()
            db.close()
            session['user_id'] = user_id
            session['username'] = username
            session['theme'] = 'light'
            return redirect(url_for('index'))
        except sqlite3.IntegrityError:
            db.close()
            return render_template('register.html', error='ชื่อผู้ใช้หรืออีเมลนี้มีอยู่แล้ว')
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or not password:
            return render_template('login.html', error='กรุณากรอกข้อมูล')
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute('SELECT * FROM users WHERE username = ?', (username,))
        user = cursor.fetchone()
        db.close()
        
        if user and user['password'] == hash_password(password):
            session['user_id'] = user['user_id']
            session['username'] = user['username']
            session['theme'] = user['theme']
            return redirect(url_for('index'))
        return render_template('login.html', error='ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

@app.route('/toggle-theme', methods=['GET', 'POST'])
def toggle_theme():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    current_theme = session.get('theme', 'light')
    new_theme = 'dark' if current_theme == 'light' else 'light'

    session['theme'] = new_theme

    db = get_db()
    cursor = db.cursor()
    cursor.execute(
        'UPDATE users SET theme = ? WHERE user_id = ?',
        (new_theme, session['user_id'])
    )
    db.commit()
    db.close()

    return redirect(request.referrer or url_for('index'))

# ===== MAIN =====
@app.route('/')
def index():
    category_id = request.args.get('category', type=int)
    search_query = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'name')
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM categories ORDER BY category_name')
    categories = cursor.fetchall()
    
    query = 'SELECT * FROM games WHERE 1=1'
    params = []
    if category_id:
        query += ' AND category_id = ?'
        params.append(category_id)
    if search_query:
        query += ' AND (name LIKE ? OR description LIKE ?)'
        params.extend([f'%{search_query}%', f'%{search_query}%'])
    
    if sort_by == 'price_low':
        query += ' ORDER BY price ASC'
    elif sort_by == 'price_high':
        query += ' ORDER BY price DESC'
    else:
        query += ' ORDER BY name ASC'
    
    cursor.execute(query, params)
    games = cursor.fetchall()
    
    games_with_ratings = []
    for game in games:
        cursor.execute('SELECT AVG(rating) as avg_rating, COUNT(*) as total_reviews FROM reviews WHERE game_id = ?', 
                      (game['game_id'],))
        review = cursor.fetchone()
        game_dict = dict(game)
        game_dict['avg_rating'] = round(review['avg_rating'], 2) if review['avg_rating'] else 0
        game_dict['total_reviews'] = review['total_reviews']
        games_with_ratings.append(game_dict)
    
    db.close()
    cart_count = get_cart_count(session.get('user_id', 0)) if session.get('user_id') else 0
    
    return render_template('index.html', games=games_with_ratings, categories=categories,
                          selected_category=category_id, search_query=search_query, 
                          sort_by=sort_by, cart_count=cart_count)
@app.route('/image/<path:url>')
def get_image(url):
    import requests
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        response = requests.get(url, timeout=5, headers=headers, allow_redirects=True)
        return response.content, 200, {'Content-Type': response.headers.get('content-type', 'image/jpeg')}
    except Exception as e:
        print(f"Error loading image: {e}")
        return '', 404
    
@app.route('/game/<int:game_id>')
def game_detail(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT g.*, c.category_name FROM games g LEFT JOIN categories c ON g.category_id = c.category_id WHERE g.game_id = ?', (game_id,))
    game = cursor.fetchone()
    
    if not game:
        db.close()
        return redirect(url_for('index'))
    
    cursor.execute('SELECT r.*, u.username FROM reviews r JOIN users u ON r.user_id = u.user_id WHERE r.game_id = ? ORDER BY r.created_at DESC', (game_id,))
    reviews = cursor.fetchall()
    
    cursor.execute('SELECT AVG(rating) as avg_rating, COUNT(*) as total_reviews FROM reviews WHERE game_id = ?', (game_id,))
    rating_info = cursor.fetchone()
    
    avg_rating = round(rating_info['avg_rating'], 2) if rating_info['avg_rating'] else 0
    
    cursor.execute('SELECT * FROM reviews WHERE user_id = ? AND game_id = ?', (session['user_id'], game_id))
    user_review = cursor.fetchone()
    
    db.close()
    game = dict(game)
  
    return render_template('game_detail.html', game=game, reviews=reviews, 
                          avg_rating=avg_rating, total_reviews=rating_info['total_reviews'],
                          user_review=user_review, cart_count=get_cart_count(session['user_id']))

# ===== CART =====
@app.route('/add-to-cart/<int:game_id>', methods=['POST'])
def add_to_cart(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM games WHERE game_id = ? AND stock > 0', (game_id,))
    if not cursor.fetchone():
        db.close()
        return redirect(request.referrer or url_for('index'))
    
    cursor.execute('SELECT cart_id FROM cart WHERE user_id = ?', (session['user_id'],))
    cart = cursor.fetchone()
    if not cart:
        db.close()
        return redirect(url_for('index'))
    
    cart_id = cart['cart_id']
    cursor.execute('SELECT * FROM cart_items WHERE cart_id = ? AND game_id = ?', (cart_id, game_id))
    item = cursor.fetchone()
    
    if item:
        cursor.execute('UPDATE cart_items SET quantity = quantity + 1 WHERE cart_item_id = ?', (item['cart_item_id'],))
    else:
        cursor.execute('INSERT INTO cart_items (cart_id, game_id, quantity) VALUES (?, ?, 1)', (cart_id, game_id))
    
    db.commit()
    db.close()
    return redirect(request.referrer or url_for('cart'))

@app.route('/cart')
def cart():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT ci.*, g.name, g.price, g.image_url FROM cart_items ci JOIN games g ON ci.game_id = g.game_id JOIN cart c ON ci.cart_id = c.cart_id WHERE c.user_id = ? ORDER BY ci.cart_item_id', 
                  (session['user_id'],))
    cart_items = cursor.fetchall()
    total_price = sum(item['price'] * item['quantity'] for item in cart_items if item['price'] > 0)
    db.close()
    
    return render_template('cart.html', cart_items=cart_items, total_price=total_price, cart_count=len(cart_items))

@app.route('/remove-from-cart/<int:cart_item_id>', methods=['POST'])
def remove_from_cart(cart_item_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    db.cursor().execute('DELETE FROM cart_items WHERE cart_item_id = ?', (cart_item_id,))
    db.commit()
    db.close()
    return redirect(url_for('cart'))

# ===== CHECKOUT =====
@app.route('/checkout', methods=['GET', 'POST'])
def checkout():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    if request.method == 'POST':
        cursor.execute('SELECT ci.*, g.price FROM cart_items ci JOIN games g ON ci.game_id = g.game_id JOIN cart c ON ci.cart_id = c.cart_id WHERE c.user_id = ?', 
                      (session['user_id'],))
        cart_items = cursor.fetchall()
        
        if not cart_items:
            db.close()
            return redirect(url_for('cart'))
        
        total_price = sum(item['price'] * item['quantity'] for item in cart_items if item['price'] > 0)
        cursor.execute('INSERT INTO orders (user_id, total_price, status) VALUES (?, ?, "paid")', 
                      (session['user_id'], total_price))
        order_id = cursor.lastrowid
        cursor.execute('DELETE FROM cart_items WHERE cart_id IN (SELECT cart_id FROM cart WHERE user_id = ?)', 
                      (session['user_id'],))
        db.commit()
        db.close()
        
        return render_template('checkout_success.html', order_id=order_id, total_price=total_price)
    
    cursor.execute('SELECT ci.*, g.name, g.price FROM cart_items ci JOIN games g ON ci.game_id = g.game_id JOIN cart c ON ci.cart_id = c.cart_id WHERE c.user_id = ?', 
                  (session['user_id'],))
    cart_items = cursor.fetchall()
    total_price = sum(item['price'] * item['quantity'] for item in cart_items if item['price'] > 0)
    db.close()
    
    return render_template('checkout.html', cart_items=cart_items, total_price=total_price, cart_count=len(cart_items))

# ===== REVIEWS =====
@app.route('/add-review/<int:game_id>', methods=['POST'])
def add_review(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    rating = request.form.get('rating', type=int)
    comment = request.form.get('comment', '').strip()
    
    if not rating or rating < 1 or rating > 5:
        return redirect(url_for('game_detail', game_id=game_id))
    
    db = get_db()
    cursor = db.cursor()
    try:
        cursor.execute('INSERT INTO reviews (user_id, game_id, rating, comment) VALUES (?, ?, ?, ?)',
                      (session['user_id'], game_id, rating, comment))
        db.commit()
    except sqlite3.IntegrityError:
        cursor.execute('UPDATE reviews SET rating = ?, comment = ? WHERE user_id = ? AND game_id = ?',
                      (rating, comment, session['user_id'], game_id))
        db.commit()
    db.close()
    
    return redirect(url_for('game_detail', game_id=game_id))

@app.route('/download/<int:game_id>')
def download_game(game_id):
    if 'user_id' not in session:
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT * FROM games WHERE game_id = ? AND price = 0', (game_id,))
    game = cursor.fetchone()
    db.close()
    
    if not game:
        return redirect(url_for('index'))
    
    return render_template('download_page.html', game=game)

# ===== API =====
@app.route('/api/cart-count')
def api_cart_count():
    if 'user_id' not in session:
        return jsonify({'count': 0})
    return jsonify({'count': get_cart_count(session['user_id'])})

@app.route('/api/search')
def api_search():
    query = request.args.get('q', '').strip()
    if len(query) < 2:
        return jsonify([])
    
    db = get_db()
    cursor = db.cursor()
    cursor.execute('SELECT game_id, name, price FROM games WHERE name LIKE ? OR description LIKE ? LIMIT 10',
                  (f'%{query}%', f'%{query}%'))
    results = cursor.fetchall()
    db.close()
    
    return jsonify([dict(row) for row in results])

@app.errorhandler(404)
def not_found(error):
    return render_template('404.html'), 404

if __name__ == '__main__':
    app.run(debug=True)