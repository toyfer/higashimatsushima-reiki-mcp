import { Hono } from 'hono';
import { createMiddleware } from 'hono/factory';
import { eq } from 'drizzle-orm';
import { drizzle } from 'drizzle-orm/d1';
import * as schema from './db/schema';

// 型定義
interface Env {
  DB: D1Database;
  JWT_SECRET: string;
}

interface JWTPayload {
  sub: string;
  role: string;
  iat: number;
  exp: number;
}

interface Variables {
  user: JWTPayload;
}

// 認証ミドルウェア
const authMiddleware = createMiddleware<{ Bindings: Env; Variables: Variables }>(
  async (c, next) => {
    const authHeader = c.req.header('Authorization');
    if (!authHeader?.startsWith('Bearer ')) {
      return c.json({ error: '認証が必要です' }, 401);
    }

    const token = authHeader.slice(7);

    try {
      const payload = await verifyJWT(token, c.env.JWT_SECRET);
      const db = drizzle(c.env.DB);
      const user = await db
        .select()
        .from(schema.users)
        .where(eq(schema.users.id, payload.sub))
        .get();

      if (!user) {
        return c.json({ error: 'ユーザーが見つかりません' }, 401);
      }

      if (user.status !== 'active') {
        return c.json({ error: 'アカウントが無効です' }, 403);
      }

      c.set('user', payload);
      await next();
    } catch (e) {
      return c.json({ error: '無効なトークンです' }, 401);
    }
  }
);

// 管理者権限チェックミドルウェア
const adminMiddleware = createMiddleware<{ Bindings: Env; Variables: Variables }>(
  async (c, next) => {
    const user = c.get('user');
    if (user.role !== 'admin') {
      return c.json({ error: '管理者権限が必要です' }, 403);
    }
    await next();
  }
);

// JWT検証関数
async function verifyJWT(token: string, secret: string): Promise<JWTPayload> {
  const [headerB64, payloadB64, signatureB64] = token.split('.');
  if (!headerB64 || !payloadB64 || !signatureB64) {
    throw new Error('Invalid token format');
  }

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['verify']
  );

  const data = encoder.encode(`${headerB64}.${payloadB64}`);
  const signature = base64UrlDecode(signatureB64);

  const valid = await crypto.subtle.verify('HMAC', key, signature, data);
  if (!valid) {
    throw new Error('Invalid signature');
  }

  const payload = JSON.parse(new TextDecoder().decode(base64UrlDecode(payloadB64)));
  
  if (payload.exp < Date.now() / 1000) {
    throw new Error('Token expired');
  }

  return payload;
}

function base64UrlDecode(str: string): Uint8Array {
  const base64 = str.replace(/-/g, '+').replace(/_/g, '/');
  const padding = '='.repeat((4 - base64.length % 4) % 4);
  const binary = atob(base64 + padding);
  return Uint8Array.from(binary, c => c.charCodeAt(0));
}

// Honoアプリケーション
const app = new Hono<{ Bindings: Env; Variables: Variables }>();

// 公開エンドポイント
app.post('/api/v1/auth/register', async (c) => {
  const { email, password, name } = await c.req.json();
  const db = drizzle(c.env.DB);

  // 既存ユーザーチェック
  const existing = await db
    .select()
    .from(schema.users)
    .where(eq(schema.users.email, email))
    .get();

  if (existing) {
    return c.json({ error: 'このメールアドレスは既に登録されています' }, 409);
  }

  // パスワードハッシュ化
  const hashedPassword = await hashPassword(password);

  // ユーザー作成
  const result = await db
    .insert(schema.users)
    .values({
      id: crypto.randomUUID(),
      email,
      name,
      passwordHash: hashedPassword,
      role: 'worker',
      status: 'pending',
      createdAt: new Date(),
      updatedAt: new Date(),
    })
    .returning()
    .get();

  return c.json({
    id: result.id,
    email: result.email,
    name: result.name,
    role: result.role,
    status: result.status,
  }, 201);
});

app.post('/api/v1/auth/login', async (c) => {
  const { email, password } = await c.req.json();
  const db = drizzle(c.env.DB);

  const user = await db
    .select()
    .from(schema.users)
    .where(eq(schema.users.email, email))
    .get();

  if (!user || !(await verifyPassword(password, user.passwordHash))) {
    return c.json({ error: 'メールアドレスまたはパスワードが間違っています' }, 401);
  }

  if (user.status !== 'active') {
    return c.json({ error: 'アカウントが承認待ちまたは無効です' }, 403);
  }

  const token = await generateJWT(user.id, user.role, c.env.JWT_SECRET);

  // 最終ログイン時間更新
  await db
    .update(schema.users)
    .set({ lastLoginAt: new Date() })
    .where(eq(schema.users.id, user.id));

  return c.json({
    token,
    user: {
      id: user.id,
      email: user.email,
      name: user.name,
      role: user.role,
    },
  });
});

// 認証が必要なエンドポイント
app.get('/api/v1/me', authMiddleware, async (c) => {
  const user = c.get('user');
  const db = drizzle(c.env.DB);

  const me = await db
    .select()
    .from(schema.users)
    .where(eq(schema.users.id, user.sub))
    .get();

  return c.json({
    id: me!.id,
    email: me!.email,
    name: me!.name,
    role: me!.role,
    status: me!.status,
  });
});

// 管理者専用エンドポイント
app.get('/api/v1/admin/users', authMiddleware, adminMiddleware, async (c) => {
  const db = drizzle(c.env.DB);
  const users = await db.select().from(schema.users).all();

  return c.json(users.map(u => ({
    id: u.id,
    email: u.email,
    name: u.name,
    role: u.role,
    status: u.status,
    createdAt: u.createdAt,
    lastLoginAt: u.lastLoginAt,
  })));
});

app.patch('/api/v1/admin/users/:id/status', authMiddleware, adminMiddleware, async (c) => {
  const id = c.req.param('id');
  const { status } = await c.req.json();
  const db = drizzle(c.env.DB);

  const updated = await db
    .update(schema.users)
    .set({ status, updatedAt: new Date() })
    .where(eq(schema.users.id, id))
    .returning()
    .get();

  if (!updated) {
    return c.json({ error: 'ユーザーが見つかりません' }, 404);
  }

  return c.json(updated);
});

// パスワード関連ユーティリティ
async function hashPassword(password: string): Promise<string> {
  const encoder = new TextEncoder();
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    encoder.encode(password),
    'PBKDF2',
    false,
    ['deriveBits']
  );
  const hash = await crypto.subtle.deriveBits(
    {
      name: 'PBKDF2',
      salt,
      iterations: 100000,
      hash: 'SHA-256',
    },
    keyMaterial,
    256
  );
  const hashArray = new Uint8Array(hash);
  const saltHex = Array.from(salt).map(b => b.toString(16).padStart(2, '0')).join('');
  const hashHex = Array.from(hashArray).map(b => b.toString(16).padStart(2, '0')).join('');
  return `${saltHex}:${hashHex}`;
}

async function verifyPassword(password: string, stored: string): Promise<boolean> {
  const [saltHex, hashHex] = stored.split(':');
  const encoder = new TextEncoder();
  const salt = new Uint8Array(saltHex.match(/.{2}/g)!.map(b => parseInt(b, 16)));
  
  const keyMaterial = await crypto.subtle.importKey(
    'raw',
    encoder.encode(password),
    'PBKDF2',
    false,
    ['deriveBits']
  );
  const hash = await crypto.subtle.deriveBits(
    {
      name: 'PBKDF2',
      salt,
      iterations: 100000,
      hash: 'SHA-256',
    },
    keyMaterial,
    256
  );
  const hashArray = new Uint8Array(hash);
  const newHashHex = Array.from(hashArray).map(b => b.toString(16).padStart(2, '0')).join('');
  
  return newHashHex === hashHex;
}

async function generateJWT(userId: string, role: string, secret: string): Promise<string> {
  const header = { alg: 'HS256', typ: 'JWT' };
  const now = Math.floor(Date.now() / 1000);
  const payload = {
    sub: userId,
    role,
    iat: now,
    exp: now + 86400, // 24時間
  };

  const encoder = new TextEncoder();
  const headerB64 = base64UrlEncode(encoder.encode(JSON.stringify(header)));
  const payloadB64 = base64UrlEncode(encoder.encode(JSON.stringify(payload)));
  
  const key = await crypto.subtle.importKey(
    'raw',
    encoder.encode(secret),
    { name: 'HMAC', hash: 'SHA-256' },
    false,
    ['sign']
  );

  const data = encoder.encode(`${headerB64}.${payloadB64}`);
  const signature = await crypto.subtle.sign('HMAC', key, data);
  const signatureB64 = base64UrlEncode(new Uint8Array(signature));

  return `${headerB64}.${payloadB64}.${signatureB64}`;
}

function base64UrlEncode(bytes: Uint8Array): string {
  const base64 = btoa(String.fromCharCode(...bytes));
  return base64.replace(/\+/g, '-').replace(/\//g, '_').replace(/=/g, '');
}

export default app;
