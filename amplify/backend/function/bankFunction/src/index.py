import json
import pymysql
import os
import random
import datetime

# --- CONFIG ---
rds_host = os.environ.get('DB_HOST')
name = os.environ.get('DB_USER')
password = os.environ.get('DB_PASS')
db_name = os.environ.get('DB_NAME')

# Helper to fix Decimal serialization error in JSON
class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, datetime.datetime):
            return str(obj)
        if isinstance(obj, float): 
            return str(obj)
        from decimal import Decimal
        if isinstance(obj, Decimal):
            return float(obj)
        return super(DecimalEncoder, self).default(obj)

def get_connection():
    return pymysql.connect(host=rds_host, user=name, passwd=password, db=db_name, connect_timeout=5, cursorclass=pymysql.cursors.DictCursor)

def handler(event, context):
    print("EVENT:", json.dumps(event))
    
    # Common Headers
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Headers': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET'
    }

    path = event.get('path')
    method = event.get('httpMethod')

    if method == 'OPTIONS':
        return {'statusCode': 200, 'headers': headers, 'body': 'OK'}

    try:
        conn = get_connection()
    except Exception as e:
        return {'statusCode': 500, 'headers': headers, 'body': json.dumps(str(e))}

    # ====================================================
    # ROUTE 1: /account (Create or Get Account)
    # ====================================================
    if '/account' in path:
        
        # POST: Create Account
        if method == 'POST':
            try:
                body = json.loads(event['body'])
                sub = body.get('sub')
                email = body.get('email')
                name_user = body.get('name')
                
                with conn.cursor() as cur:
                    # Check if exists
                    cur.execute("SELECT * FROM customers WHERE cognito_sub = %s", (sub,))
                    if cur.fetchone():
                        return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'msg': 'User exists'})}

                    # Create New
                    acc_num = str(random.randint(1000000000, 9999999999))
                    # Bonus $1000 for signing up
                    sql = "INSERT INTO customers (cognito_sub, email, full_name, account_number, balance) VALUES (%s, %s, %s, %s, %s)"
                    cur.execute(sql, (sub, email, name_user, acc_num, 1000.00))
                    conn.commit()
                    return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'account': acc_num, 'balance': 1000})}
            except Exception as e:
                return {'statusCode': 500, 'headers': headers, 'body': json.dumps(str(e))}

        # GET: Get Balance
        elif method == 'GET':
            sub = event.get('queryStringParameters', {}).get('sub')
            with conn.cursor() as cur:
                cur.execute("SELECT email, account_number, balance FROM customers WHERE cognito_sub=%s", (sub,))
                res = cur.fetchone()
                if res:
                    return {'statusCode': 200, 'headers': headers, 'body': json.dumps(res, cls=DecimalEncoder)}
                return {'statusCode': 404, 'headers': headers, 'body': json.dumps("User not found")}

    # ====================================================
    # ROUTE 2: /transaction (Transfer Money)
    # ====================================================
    elif '/transaction' in path:
        
        # POST: Transfer Money
        if method == 'POST':
            try:
                body = json.loads(event['body'])
                sender_sub = body.get('sub') # Authenticated User
                receiver_acc = body.get('to_account')
                amount = float(body.get('amount'))

                if amount <= 0:
                    return {'statusCode': 400, 'headers': headers, 'body': json.dumps("Invalid amount")}

                conn.begin() # START TRANSACTION (ACID)
                try:
                    with conn.cursor() as cur:
                        # 1. Get Sender Info
                        cur.execute("SELECT account_number, balance FROM customers WHERE cognito_sub=%s", (sender_sub,))
                        sender = cur.fetchone()
                        if not sender:
                            raise Exception("Sender not found")
                        
                        sender_acc_num = sender['account_number']
                        current_bal = float(sender['balance'])

                        if current_bal < amount:
                            raise Exception("Insufficient funds")

                        # 2. Check Receiver Exists
                        cur.execute("SELECT account_number FROM customers WHERE account_number=%s", (receiver_acc,))
                        receiver = cur.fetchone()
                        if not receiver:
                            raise Exception("Receiver account does not exist")

                        # 3. Deduct from Sender
                        cur.execute("UPDATE customers SET balance = balance - %s WHERE account_number = %s", (amount, sender_acc_num))

                        # 4. Add to Receiver
                        cur.execute("UPDATE customers SET balance = balance + %s WHERE account_number = %s", (amount, receiver_acc))

                        # 5. Log Transaction
                        sql_log = "INSERT INTO transactions (sender_account, receiver_account, amount, type) VALUES (%s, %s, %s, 'TRANSFER')"
                        cur.execute(sql_log, (sender_acc_num, receiver_acc, amount))
                    
                    conn.commit() # SAVE CHANGES
                    return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'msg': 'Transfer Successful', 'new_balance': current_bal - amount})}
                
                except Exception as e:
                    conn.rollback() # UNDO CHANGES IF ERROR
                    return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'error': str(e)})}
            
            except Exception as outer_e:
                return {'statusCode': 500, 'headers': headers, 'body': json.dumps(str(outer_e))}
        
        # GET: Transaction History
        elif method == 'GET':
            sub = event.get('queryStringParameters', {}).get('sub')
            with conn.cursor() as cur:
                # Get Account Num first
                cur.execute("SELECT account_number FROM customers WHERE cognito_sub=%s", (sub,))
                user = cur.fetchone()
                if not user:
                    return {'statusCode': 404, 'headers': headers, 'body': json.dumps("User not found")}
                
                acc_num = user['account_number']
                
                # Get transactions where user is Sender OR Receiver
                sql = "SELECT * FROM transactions WHERE sender_account = %s OR receiver_account = %s ORDER BY created_at DESC LIMIT 10"
                cur.execute(sql, (acc_num, acc_num))
                history = cur.fetchall()
                
                return {'statusCode': 200, 'headers': headers, 'body': json.dumps(history, cls=DecimalEncoder)}

    return {'statusCode': 400, 'headers': headers, 'body': json.dumps("Invalid Path")}