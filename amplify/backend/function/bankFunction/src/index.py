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
    # ROUTE 1: /account (Create or Get Account or Verify User)
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

            params = event.get('queryStringParameters') or {}

            if 'sub' in params:
                sub = params['sub']
                with conn.cursor() as cur:
                    cur.execute("SELECT email, account_number, balance FROM customers WHERE cognito_sub=%s", (sub,))
                    res = cur.fetchone()
                    if res:
                        return {'statusCode': 200, 'headers': headers, 'body': json.dumps(res, cls=DecimalEncoder)}
                    else:
                        return {'statusCode': 404, 'headers': headers, 'body': json.dumps("User not found")}
            

            #Get the User to verify before payment

            if 'verify_account' in params:
                target_acc = params['verify_account']
            ##target_acc = event.get('queryStringParameters' , {}).get('verify_account')
                if target_acc:
                    with conn.cursor() as cur:
                        cur.execute("Select full_name from customers where account_number = %s" ,(target_acc))
                        user = cur.fetchone()
    
                        if user :
                            return {'statusCode' :200 , 'headers':headers , 'body':json.dumps({'name':user['full_name']})}
                        else:
                            return {'statusCode':404 , 'headers' :headers, 'body':json.dumps({'error':'Account not found'})}

    # ====================================================
    # ROUTE 2: /transaction (Transfer, Deposit, Withdraw, Histor)
    # ====================================================
    # ====================================================
    # ROUTE 2: /transaction (Transfer, Deposit, Withdraw, History)
    # ====================================================
    elif '/transaction' in path:
        
        # ------------------------------------------------
        # POST: Perform a Transaction
        # ------------------------------------------------
        if method == 'POST':
            try:
                body = json.loads(event['body'])
                trans_type = body.get('type', 'TRANSFER') # Default to TRANSFER
                amount = float(body.get('amount'))

                if amount <= 0:
                    return {'statusCode': 400, 'headers': headers, 'body': json.dumps("Invalid amount")}

                conn.begin() # START TRANSACTION (ACID)
                try:
                    with conn.cursor() as cur:
                        
                        # --- SCENARIO A: DEPOSIT (ATM) ---
                        if trans_type == 'DEPOSIT':
                            target_acc = body.get('to_account')
                            # 1. Add Money
                            cur.execute("UPDATE customers SET balance = balance + %s WHERE account_number = %s", (amount, target_acc))
                            # 2. Log it
                            cur.execute("INSERT INTO transactions (receiver_account, amount, type) VALUES (%s, %s, 'DEPOSIT')", (target_acc, amount))
                            msg = "Deposit Successful"

                        # --- SCENARIO B: WITHDRAWAL (ATM) ---
                        elif trans_type == 'WITHDRAWAL':
                            target_acc = body.get('from_account') # The user's account
                            # 1. Check Balance
                            cur.execute("SELECT balance FROM customers WHERE account_number=%s", (target_acc,))
                            res = cur.fetchone()
                            if not res or float(res['balance']) < amount:
                                raise Exception("Insufficient Funds")
                            
                            # 2. Deduct Money
                            cur.execute("UPDATE customers SET balance = balance - %s WHERE account_number = %s", (amount, target_acc))
                            # 3. Log it
                            cur.execute("INSERT INTO transactions (sender_account, amount, type) VALUES (%s, %s, 'WITHDRAWAL')", (target_acc, amount))
                            msg = "Withdrawal Successful"

                        # --- SCENARIO C: TRANSFER (P2P) ---
                        else:
                            sender_sub = body.get('sub')
                            receiver_acc = body.get('to_account')

                            # Get Sender Account Number
                            cur.execute("SELECT account_number, balance FROM customers WHERE cognito_sub=%s", (sender_sub,))
                            sender = cur.fetchone()
                            if not sender: raise Exception("Sender not found")
                            
                            sender_acc = sender['account_number']
                            if float(sender['balance']) < amount: raise Exception("Insufficient funds")

                            # Execute Transfer
                            cur.execute("UPDATE customers SET balance = balance - %s WHERE account_number = %s", (amount, sender_acc))
                            cur.execute("UPDATE customers SET balance = balance + %s WHERE account_number = %s", (amount, receiver_acc))
                            cur.execute("INSERT INTO transactions (sender_account, receiver_account, amount, type) VALUES (%s, %s, %s, 'TRANSFER')", (sender_acc, receiver_acc, amount))
                            msg = "Transfer Successful"
                    
                    conn.commit() # Save Changes
                    return {'statusCode': 200, 'headers': headers, 'body': json.dumps({'msg': msg})}
                
                except Exception as e:
                    conn.rollback() # Undo if error
                    return {'statusCode': 400, 'headers': headers, 'body': json.dumps({'error': str(e)})}
            
            except Exception as e:
                return {'statusCode': 500, 'headers': headers, 'body': json.dumps(str(e))}
        
        # ------------------------------------------------
        # GET: Transaction History with FILTERS
        # ------------------------------------------------
        elif method == 'GET':
            params = event.get('queryStringParameters') or {}
            sub = params.get('sub')
            filter_type = params.get('type') # Optional: FILTER by DEPOSIT/TRANSFER
            
            with conn.cursor() as cur:
                # 1. Get Account Number first
                cur.execute("SELECT account_number FROM customers WHERE cognito_sub=%s", (sub,))
                user = cur.fetchone()
                if not user:
                    return {'statusCode': 404, 'headers': headers, 'body': json.dumps("User not found")}
                
                acc_num = user['account_number']
                
                # 2. Build Dynamic SQL
                sql = "SELECT * FROM transactions WHERE (sender_account = %s OR receiver_account = %s)"
                query_args = [acc_num, acc_num]

                # Add Filter if provided
                if filter_type:
                    sql += " AND type = %s"
                    query_args.append(filter_type)
                
                sql += " ORDER BY created_at DESC LIMIT 10"

                cur.execute(sql, tuple(query_args))
                history = cur.fetchall()
                
                return {'statusCode': 200, 'headers': headers, 'body': json.dumps(history, cls=DecimalEncoder)}

    return {'statusCode': 400, 'headers': headers, 'body': json.dumps("Invalid Path")}