# 発展課題
[課題リンク](https://www.coins.tsukuba.ac.jp/~amagasa/lecture/dsa-jikken/report1/#_5)

`gcd_euclid` を，再帰的アルゴリズム（教科書p. 14）に基づいて書き換えた `gcd_recursive.c` および `main_recursive.c` を作成しなさい．関数名は `gcd_recursive` とする．

## ファイル gcd_recursive.c
```c
#include <stdio.h>
#include <stdlib.h>

// Find the greatest common divisor of the two integers, n and m.
int gcd_recursive(int n, int m) {

    // 関数を完成させよ

    return n;
}
```

## ファイル main_recursive.c
```c
#include <stdio.h>
#include <stdlib.h>

// Find the greatest common divisor of the two integers, n and m.
int gcd_recursive(int, int);

int main(int argc, char *argv[]) {
  // Process arguments.
  if (argc != 3) {
    fprintf(stderr, "Usage: %s <number1> <number2>\n", argv[0]);
    return EXIT_FAILURE;
  }
  int n = atoi(argv[1]);
  int m = atoi(argv[2]);

  // Compute and output the greatest common divisor.
  int gcd = gcd_recursive(n, m);
  printf("The GCD of %d and %d is %d.\n", n, m, gcd);

  return EXIT_SUCCESS;
}
```


# 提出方法
基本課題・発展課題をまとめて、次の5ファイルを提出ルート直下に配置して提出せよ。小問ごとのフォルダには分けない。1つの提出に両方の課題を実行する。

- `gcd_euclid.c`
- `main_euclid.c`
- `gcd_recursive.c`
- `main_recursive.c`
- 共通の `Makefile`

共通Makefileには両方のターゲットを定義する。

```make
.PHONY: all
all: gcd_euclid gcd_recursive

gcd_euclid: gcd_euclid.o main_euclid.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)

gcd_recursive: gcd_recursive.o main_recursive.o
	$(CC) $(LDFLAGS) -o $@ $^ $(LDLIBS)
```
