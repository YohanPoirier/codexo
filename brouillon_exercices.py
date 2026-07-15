





## Fonctions

def diff_et_somme(a,b):
    """Renvoie la somme et le produit de a et b"""

    return a+b, a-b


##Chaines de caractères

def nombre_de_lettres(mot):
    return len(mot)

def premiere_lettre(mot):
    return mot[0]


def derniere_lettre(mot):
    return mot[-1]


def tranche_mot(mot,a,b):

    return mot[a:-b]





def repetition(lettre, n):
    return n*lettre


def concatenation(mot1,mot2):
    return mot1+mot2


def mot_a_trou(mot,lettre):

    mot2 = ""
    for l in mot :
        if l != lettre :
            mot2 += l
        else :
            mot2 += "_"

    return mot2


def consonnes(mot):

    voyelles = "aeiouy"
    mot2 = ""
    for lettre in mot :
        if lettre not in voyelles :
            mot2 += lettre

    return mot2


def contient_mot(phrase,mot):

    n_m = len(mot)
    n_p = len(phrase)

    for i in range(n_p-n_m):
        if phrase[i:i+n_m] == mot :
            return True

    return False


##Boucles



def puissance_de_2(x):

    nb = 1

    n = 0

    while nb < x :
        nb *= 2
        n += 1

    return n

def somme_pairs(n):

    somme = 0
    for i in range(0,n,2):
        somme += i

    return somme


def somme_chiffres_entier(n):

    chaine = str(n)

    somme = 0
    for i in range(len(chaine)):
        somme += int(chaine[i])

    return somme


def pgcd(a, b):
    while a != b:
        if a > b:
            a = a - b
        else:
            b = b - a
    return a


def est_premier(n):
    if n < 2:
        return False

    for diviseur in range(2, n):
        if n % diviseur == 0:
            return False

    return True


def nombre_diviseurs(n):
    compteur = 0

    for diviseur in range(1, n + 1):
        if n % diviseur == 0:
            compteur += 1

    return compteur


def comparaison_placements(capital_initial, versement_B):
    placement_A = capital_initial
    placement_B = capital_initial

    annees = 0

    while placement_B <= placement_A:
        placement_A = placement_A * 1.02
        placement_B = placement_B * 1.01 + versement_B

        annees += 1

    return annees


def est_palindrome(mot):
    n = len(mot)

    for i in range(n//2):
        if mot[i] != mot[-1-i]:
            return False

    return True