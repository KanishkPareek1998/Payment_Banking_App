import React, { useState, useEffect, useCallback } from 'react'; // Added useCallback
import { get, post } from 'aws-amplify/api';
import { Authenticator, useAuthenticator } from '@aws-amplify/ui-react';
import '@aws-amplify/ui-react/styles.css';
import { Amplify } from 'aws-amplify';
import config from './amplifyconfiguration.json';
import './App.css';

Amplify.configure(config);

export default function App() {
  const [details, setDetails] = useState(null);
  const [loading, setLoading] = useState(false);

  const { user, signOut, authStatus } = useAuthenticator((context) => [
    context.user,
    context.authStatus,
  ]);

  // --- 1. Define createAccount with useCallback ---
  const createAccount = useCallback(async (currentUser) => {
    try {
      console.log("User new to bank. Creating account...");
      const payload = {
        sub: currentUser.userId || currentUser.attributes?.sub,
        email: currentUser.signInDetails?.loginId || currentUser.attributes?.email,
        name: currentUser.username
      };

      const restOperation = post({
        apiName: 'BankAPI',
        path: '/accounts',
        options: { body: payload }
      });

      await restOperation.response;
      // We don't call fetchAccount here anymore; the useEffect will handle it
      setDetails(null); 
    } catch (err) {
      console.error("Failed to create account:", err);
    }
  }, []);

  // --- 2. Define fetchAccount with useCallback ---
  // const fetchAccount = useCallback(async (currentUser) => {
  //   setLoading(true);
  //   try {
  //     const userSub = currentUser.userId || currentUser.attributes?.sub;
  //     const restOperation = get({
  //       apiName: 'BankAPI',
  //       path: `/accounts?sub=${userSub}`
  //     });
  //     const { response } = await restOperation;
  //     const data = await response.body.json();
  //     setDetails(data);
  //   } catch (err) {
  //     console.log("Error fetching account:", err);
  //     // If 404, trigger creation
  //     if (err.response && err.response.statusCode === 404) {
  //       createAccount(currentUser);
  //     }
  //   } finally {
  //     setLoading(false);
  //   }
  // }, [createAccount]); 
     const fetchAccount = useCallback(async (currentUser) => {
  if (!currentUser) return;
  setLoading(true);

  try {
    const userSub = currentUser.userId || currentUser.attributes?.sub;
    
    const restOperation = get({
      apiName: 'BankAPI',
      path: `/accounts?sub=${userSub}`
    });

    const { response } = await restOperation;

    // Handle 404: Account doesn't exist yet
    if (response.statusCode === 404) {
      console.log("Account not found (404). Initiating creation...");
      await createAccount(currentUser);
      return; 
    }

    // Handle 200: Account exists
    const data = await response.body.json();
    setDetails(data);

  } catch (err) {
    /* If your API Gateway returns 404 as a hard error instead of a statusCode, 
       Amplify will catch it here.
    */
    const is404 = err.response?.statusCode === 404 || err.message?.includes('404');
    
    if (is404) {
      await createAccount(currentUser);
    } else {
      console.error("Unexpected error during fetch:", err);
    }
  } finally {
    setLoading(false);
  }
}, [createAccount]); // createAccount is now a stable dependency   // fetchAccount depends on createAccount

  // --- 3. useEffect now has stable dependencies ---
  useEffect(() => {
    if (authStatus === 'authenticated' && user && !details && !loading) {
      fetchAccount(user);
    }
  }, [authStatus, user, details, loading, fetchAccount]); // All dependencies included!

  if (authStatus !== 'authenticated') {
    return <Authenticator />;
  }

  return (
    <div className="App">
      <header className="App-header">
        <h1>🏦 Cloud Bank</h1>
        <p>Welcome back, {user?.username}</p>
      </header>

      <main>
        {loading ? (
          <p>Loading your financial data...</p>
        ) : details ? (
          <div className="card">
            <h2>Your Account Overview</h2>
            <div className="detail-row">
              <span>Account Number:</span>
              <strong>{details.account}</strong>
            </div>
            <div className="detail-row">
              <span>Current Balance:</span>
              <strong className="balance">${details.balance}</strong>
            </div>
          </div>
        ) : (
          <p>Setting up your account...</p>
        )}
        <button className="logout-btn" onClick={signOut}>Sign Out</button>
      </main>
    </div>
  );
}