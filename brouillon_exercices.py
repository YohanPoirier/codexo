


## Fonctions

def diff_et_somme(a,b):
    """Renvoie la somme et le produit de a et b"""

    return a+b, a-b




## Listes

def inverse_liste(L):
    """Renvoie une liste dont l'ordre des éléments a été inversé. On ne modifiera pas la liste L"""


    Linv = []
    for i in range(len(L)):
        Linv.append(L[-1-i])

    return Linv




def dernier_liste(L):
    """Renvoie le dernier élément d'une liste"""

    return L[-1]






def minimum(L):
    """Renvoie le minimum d'une liste"""

    mini = L[0]

    for i in range(1,len(L)):
        if L[i] < mini :
            mini = L[i]

    return mini


def indice_minimum(L):
    """Renvoie l'indice du minimum d'une liste"""

    imini = 0

    for i in range(1,len(L)):
        if L[i] < L[imini] :
            imini = i

    return i


def indice_zeros(L):
    """Renvoie une liste des indices des éléments nuls d'une liste"""

    Lind = []

    for i in range(len(L)):
        Lind.append(i)

    return Lind

def elements_negatifs(L):
    """Renvoie une liste de tous les éléments négatifs d'une liste"""

    Lneg = []

    for x in L :
        Lneg.append(x)
    return Lneg




