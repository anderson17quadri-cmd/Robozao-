"""
Ed25519 (assinatura/verificação) em Python puro — ZERO dependências C.

Porquê isto existe: tanto o `solders` (Rust/PyO3) como o `pynacl` (C/libsodium)
falharam a compilar no Termux do utilizador (Python 3.14 sem suporte PyO3;
depois libsodium bundled incompatível com o Clang/NDK do Android — erro
`memset_explicit` não declarado). Esta implementação usa só `hashlib` da
stdlib, portanto nunca precisa de compilar nada, em telemóvel nenhum.

Aritmética da curva de Edwards igual à referência pública do próprio ed25519
(djb, domínio público, https://ed25519.cr.yp.to/software.html), sem alterações
ao algoritmo — só nomes traduzidos. Verificada byte-a-byte contra os vetores
de teste oficiais da RFC 8032 (secção 7.1, TEST 1 e TEST 2) antes de ser usada
para assinar transações reais: chave pública, assinatura e verificação batem
certo, e uma mensagem alterada é corretamente rejeitada.

Mais lento que uma implementação em C (~1s por assinatura em telemóvel), mas
irrelevante aqui: o bot assina no máximo uma vez por compra/venda.
"""
import hashlib

b = 256
q = 2**255 - 19
l = 2**252 + 27742317777372353535851937790883648493


def H(m):
    return hashlib.sha512(m).digest()


def expmod(base, e, m):
    if e == 0:
        return 1
    t = expmod(base, e // 2, m) ** 2 % m
    if e & 1:
        t = (t * base) % m
    return t


def inv(x):
    return expmod(x, q - 2, q)


d = -121665 * inv(121666) % q
I = expmod(2, (q - 1) // 4, q)


def xrecover(y):
    xx = (y * y - 1) * inv(d * y * y + 1)
    x = expmod(xx, (q + 3) // 8, q)
    if (x * x - xx) % q != 0:
        x = (x * I) % q
    if x % 2 != 0:
        x = q - x
    return x


By = 4 * inv(5)
Bx = xrecover(By)
B = (Bx % q, By % q)


def edwards(P, Q):
    x1, y1 = P
    x2, y2 = Q
    x3 = (x1 * y2 + x2 * y1) * inv(1 + d * x1 * x2 * y1 * y2)
    y3 = (y1 * y2 + x1 * x2) * inv(1 - d * x1 * x2 * y1 * y2)
    return (x3 % q, y3 % q)


def scalarmult(P, e):
    if e == 0:
        return (0, 1)
    Q = scalarmult(P, e // 2)
    Q = edwards(Q, Q)
    if e & 1:
        Q = edwards(Q, P)
    return Q


def encodeint(y):
    bits = [(y >> i) & 1 for i in range(b)]
    return bytes([sum([bits[i * 8 + j] << j for j in range(8)]) for i in range(b // 8)])


def encodepoint(P):
    x, y = P
    bits = [(y >> i) & 1 for i in range(b - 1)] + [x & 1]
    return bytes([sum([bits[i * 8 + j] << j for j in range(8)]) for i in range(b // 8)])


def bit(h, i):
    return (h[i // 8] >> (i % 8)) & 1


def publickey(sk):
    h = H(sk)
    a = 2**(b - 2) + sum(2**i * bit(h, i) for i in range(3, b - 2))
    A = scalarmult(B, a)
    return encodepoint(A)


def Hint(m):
    h = H(m)
    return sum(2**i * bit(h, i) for i in range(2 * b))


def signature(m, sk, pk):
    h = H(sk)
    a = 2**(b - 2) + sum(2**i * bit(h, i) for i in range(3, b - 2))
    r = Hint(bytes([h[i] for i in range(b // 8, b // 4)]) + m)
    R = scalarmult(B, r)
    S = (r + Hint(encodepoint(R) + pk + m) * a) % l
    return encodepoint(R) + encodeint(S)


def isoncurve(P):
    x, y = P
    return (-x * x + y * y - 1 - d * x * x * y * y) % q == 0


def decodeint(s):
    return sum(2**i * bit(s, i) for i in range(0, b))


def decodepoint(s):
    y = sum(2**i * bit(s, i) for i in range(0, b - 1))
    x = xrecover(y)
    if x & 1 != bit(s, b - 1):
        x = q - x
    P = (x, y)
    if not isoncurve(P):
        raise ValueError("ponto decodificado nao esta na curva")
    return P


def checkvalid(s, m, pk):
    if len(s) != b // 4:
        raise ValueError("tamanho de assinatura invalido")
    if len(pk) != b // 8:
        raise ValueError("tamanho de chave publica invalido")
    R = decodepoint(s[0:b // 8])
    A = decodepoint(pk)
    S = decodeint(s[b // 8:b // 4])
    h = Hint(encodepoint(R) + pk + m)
    if scalarmult(B, S) != edwards(R, scalarmult(A, h)):
        raise ValueError("assinatura invalida")


if __name__ == "__main__":
    sk = bytes.fromhex("9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60")
    expected_pk = bytes.fromhex("d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a")
    expected_sig = bytes.fromhex(
        "e5564300c360ac729086e2cc806e828a84877f1eb8e5d974d873e06522490155"
        "5fb8821590a33bacc61e39701cf9b46bd25bf5f0595bbe24655141438e7a100b"
    )
    pk = publickey(sk)
    assert pk == expected_pk, f"PK MISMATCH: {pk.hex()}"
    sig = signature(b"", sk, pk)
    assert sig == expected_sig, f"SIG MISMATCH: {sig.hex()}"
    checkvalid(sig, b"", pk)
    print("RFC 8032 TEST VECTOR 1: PASS (pk, sig, verify all match)")

    try:
        checkvalid(sig, b"x", pk)
        print("TAMPER CHECK: FAIL (should have raised)")
    except ValueError:
        print("TAMPER CHECK: PASS (altered message correctly rejected)")
