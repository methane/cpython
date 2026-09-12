
Tools/jit/tier3_data/native_acceptance/squares.bin:     file format binary


Disassembly of section .data:

0000000000000000 <.data>:
       0:	48 89 fb             	mov    %rdi,%rbx
       3:	4d 89 a7 30 01 00 00 	mov    %r12,0x130(%r15)
       a:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      10:	74 05                	je     0x17
      12:	48 89 df             	mov    %rbx,%rdi
      15:	eb 35                	jmp    0x4c
      17:	48 83 ec 18          	sub    $0x18,%rsp
      1b:	4d 89 75 40          	mov    %r14,0x40(%r13)
      1f:	49 8b bf 38 01 00 00 	mov    0x138(%r15),%rdi
      26:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
      2b:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
      30:	ff 15 85 0b 00 00    	call   *0xb85(%rip)        # 0xbbb
      36:	48 89 df             	mov    %rbx,%rdi
      39:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
      3e:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
      43:	48 83 c4 18          	add    $0x18,%rsp
      47:	e9 0f 08 00 00       	jmp    0x85b
      4c:	41 c6 44 24 24 00    	movb   $0x0,0x24(%r12)
      52:	48 b8 ba 7b cc 1e 57 	movabs $0x7f571ecc7bba,%rax
      59:	7f 00 00 
      5c:	49 89 45 38          	mov    %rax,0x38(%r13)
      60:	4d 89 75 40          	mov    %r14,0x40(%r13)
      64:	49 8b 47 18          	mov    0x18(%r15),%rax
      68:	84 c0                	test   %al,%al
      6a:	74 3b                	je     0xa7
      6c:	48 83 ec 18          	sub    $0x18,%rsp
      70:	48 89 7c 24 10       	mov    %rdi,0x10(%rsp)
      75:	4c 89 ff             	mov    %r15,%rdi
      78:	4c 89 64 24 08       	mov    %r12,0x8(%rsp)
      7d:	49 89 d4             	mov    %rdx,%r12
      80:	48 89 f3             	mov    %rsi,%rbx
      83:	ff 15 12 0b 00 00    	call   *0xb12(%rip)        # 0xb9b
      89:	48 8b 7c 24 10       	mov    0x10(%rsp),%rdi
      8e:	4c 89 e2             	mov    %r12,%rdx
      91:	4c 8b 64 24 08       	mov    0x8(%rsp),%r12
      96:	85 c0                	test   %eax,%eax
      98:	48 8d 64 24 18       	lea    0x18(%rsp),%rsp
      9d:	74 08                	je     0xa7
      9f:	48 89 de             	mov    %rbx,%rsi
      a2:	e9 f7 07 00 00       	jmp    0x89e
      a7:	31 ff                	xor    %edi,%edi
      a9:	31 f6                	xor    %esi,%esi
      ab:	31 d2                	xor    %edx,%edx
      ad:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
      b3:	0f 84 19 08 00 00    	je     0x8d2
      b9:	49 8b 46 f0          	mov    -0x10(%r14),%rax
      bd:	48 89 c1             	mov    %rax,%rcx
      c0:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
      c4:	49 b8 20 8c 4e 4f 4d 	movabs $0x564d4f4e8c20,%r8
      cb:	56 00 00 
      ce:	4c 39 41 08          	cmp    %r8,0x8(%rcx)
      d2:	0f 85 3d 08 00 00    	jne    0x915
      d8:	49 8b 76 f8          	mov    -0x8(%r14),%rsi
      dc:	49 83 c6 f0          	add    $0xfffffffffffffff0,%r14
      e0:	48 89 c7             	mov    %rax,%rdi
      e3:	48 89 f8             	mov    %rdi,%rax
      e6:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
      ea:	48 83 78 20 00       	cmpq   $0x0,0x20(%rax)
      ef:	0f 8e 45 08 00 00    	jle    0x93a
      f5:	48 83 ec 78          	sub    $0x78,%rsp
      f9:	49 89 f8             	mov    %rdi,%r8
      fc:	48 b8 23 00 00 00 00 	movabs $0x23,%rax
     103:	00 00 00 
     106:	0f b7 d8             	movzwl %ax,%ebx
     109:	c1 eb 04             	shr    $0x4,%ebx
     10c:	48 89 f9             	mov    %rdi,%rcx
     10f:	48 83 e1 fe          	and    $0xfffffffffffffffe,%rcx
     113:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     118:	c7 44 24 64 00 00 00 	movl   $0x0,0x64(%rsp)
     11f:	00 
     120:	48 b8 20 8c 4e 4f 4d 	movabs $0x564d4f4e8c20,%rax
     127:	56 00 00 
     12a:	48 39 41 08          	cmp    %rax,0x8(%rcx)
     12e:	0f 85 64 04 00 00    	jne    0x598
     134:	48 83 79 18 01       	cmpq   $0x1,0x18(%rcx)
     139:	0f 85 59 04 00 00    	jne    0x598
     13f:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     143:	48 b8 00 1c 4e 4f 4d 	movabs $0x564d4f4e1c00,%rax
     14a:	56 00 00 
     14d:	48 39 47 08          	cmp    %rax,0x8(%rdi)
     151:	0f 85 41 04 00 00    	jne    0x598
     157:	48 89 4c 24 68       	mov    %rcx,0x68(%rsp)
     15c:	4c 89 64 24 28       	mov    %r12,0x28(%rsp)
     161:	4c 89 7c 24 20       	mov    %r15,0x20(%rsp)
     166:	48 89 54 24 48       	mov    %rdx,0x48(%rsp)
     16b:	4c 89 44 24 08       	mov    %r8,0x8(%rsp)
     170:	4d 89 06             	mov    %r8,(%r14)
     173:	48 89 74 24 18       	mov    %rsi,0x18(%rsp)
     178:	49 89 76 08          	mov    %rsi,0x8(%r14)
     17c:	4c 89 74 24 38       	mov    %r14,0x38(%rsp)
     181:	49 83 c6 10          	add    $0x10,%r14
     185:	4c 89 6c 24 10       	mov    %r13,0x10(%rsp)
     18a:	4d 89 75 40          	mov    %r14,0x40(%r13)
     18e:	48 8d 74 24 64       	lea    0x64(%rsp),%rsi
     193:	ff 15 2a 0a 00 00    	call   *0xa2a(%rip)        # 0xbc3
     199:	49 89 c7             	mov    %rax,%r15
     19c:	48 83 f8 ff          	cmp    $0xffffffffffffffff,%rax
     1a0:	0f 84 ae 00 00 00    	je     0x254
     1a6:	4d 89 f9             	mov    %r15,%r9
     1a9:	4c 89 74 24 70       	mov    %r14,0x70(%rsp)
     1ae:	83 7c 24 64 00       	cmpl   $0x0,0x64(%rsp)
     1b3:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     1b8:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     1bd:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     1c2:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     1c7:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     1cc:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     1d1:	48 8b 4c 24 68       	mov    0x68(%rsp),%rcx
     1d6:	0f 85 bc 03 00 00    	jne    0x598
     1dc:	48 8b 51 20          	mov    0x20(%rcx),%rdx
     1e0:	48 83 fa 02          	cmp    $0x2,%rdx
     1e4:	0f 8c ae 03 00 00    	jl     0x598
     1ea:	49 8b 45 00          	mov    0x0(%r13),%rax
     1ee:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     1f2:	4c 8b 90 a8 00 00 00 	mov    0xa8(%rax),%r10
     1f9:	48 8b 49 10          	mov    0x10(%rcx),%rcx
     1fd:	41 8a 7c 24 22       	mov    0x22(%r12),%dil
     202:	40 84 ff             	test   %dil,%dil
     205:	41 0f 94 c3          	sete   %r11b
     209:	49 8b 47 18          	mov    0x18(%r15),%rax
     20d:	4c 39 d0             	cmp    %r10,%rax
     210:	0f 95 c0             	setne  %al
     213:	89 44 24 30          	mov    %eax,0x30(%rsp)
     217:	44 89 5c 24 60       	mov    %r11d,0x60(%rsp)
     21c:	44 08 d8             	or     %r11b,%al
     21f:	a8 01                	test   $0x1,%al
     221:	74 67                	je     0x28a
     223:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     228:	b8 01 00 00 00       	mov    $0x1,%eax
     22d:	48 c7 44 24 58 00 00 	movq   $0x0,0x58(%rsp)
     234:	00 00 
     236:	48 c7 44 24 40 00 00 	movq   $0x0,0x40(%rsp)
     23d:	00 00 
     23f:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     246:	00 
     247:	8b 4c 24 30          	mov    0x30(%rsp),%ecx
     24b:	8b 54 24 60          	mov    0x60(%rsp),%edx
     24f:	e9 4d 01 00 00       	jmp    0x3a1
     254:	ff 15 71 09 00 00    	call   *0x971(%rip)        # 0xbcb
     25a:	48 85 c0             	test   %rax,%rax
     25d:	0f 84 43 ff ff ff    	je     0x1a6
     263:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     268:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     26d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     272:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     277:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     27c:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     281:	48 83 c4 78          	add    $0x78,%rsp
     285:	e9 30 07 00 00       	jmp    0x9ba
     28a:	4c 8d 42 ff          	lea    -0x1(%rdx),%r8
     28e:	48 8d 34 0a          	lea    (%rdx,%rcx,1),%rsi
     292:	48 83 c6 fe          	add    $0xfffffffffffffffe,%rsi
     296:	48 8d 04 0a          	lea    (%rdx,%rcx,1),%rax
     29a:	48 ff c8             	dec    %rax
     29d:	48 89 44 24 30       	mov    %rax,0x30(%rsp)
     2a2:	48 83 c2 fe          	add    $0xfffffffffffffffe,%rdx
     2a6:	b8 01 00 00 00       	mov    $0x1,%eax
     2ab:	45 31 f6             	xor    %r14d,%r14d
     2ae:	45 31 ed             	xor    %r13d,%r13d
     2b1:	49 89 cb             	mov    %rcx,%r11
     2b4:	4e 8d 24 31          	lea    (%rcx,%r14,1),%r12
     2b8:	4d 0f af e4          	imul   %r12,%r12
     2bc:	0f 80 82 00 00 00    	jo     0x344
     2c2:	4d 01 cc             	add    %r9,%r12
     2c5:	70 7d                	jo     0x344
     2c7:	4c 39 f2             	cmp    %r14,%rdx
     2ca:	0f 84 8d 00 00 00    	je     0x35d
     2d0:	4c 8b 4c 24 20       	mov    0x20(%rsp),%r9
     2d5:	4d 8b 49 18          	mov    0x18(%r9),%r9
     2d9:	49 ff c6             	inc    %r14
     2dc:	4d 39 d1             	cmp    %r10,%r9
     2df:	41 0f 95 c7          	setne  %r15b
     2e3:	75 11                	jne    0x2f6
     2e5:	4d 89 dd             	mov    %r11,%r13
     2e8:	49 ff c3             	inc    %r11
     2eb:	48 ff c0             	inc    %rax
     2ee:	4d 89 e1             	mov    %r12,%r9
     2f1:	40 84 ff             	test   %dil,%dil
     2f4:	75 be                	jne    0x2b4
     2f6:	4d 89 e1             	mov    %r12,%r9
     2f9:	49 8d 46 01          	lea    0x1(%r14),%rax
     2fd:	4a 8d 14 31          	lea    (%rcx,%r14,1),%rdx
     301:	48 ff ca             	dec    %rdx
     304:	48 89 54 24 58       	mov    %rdx,0x58(%rsp)
     309:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     30e:	4c 01 f1             	add    %r14,%rcx
     311:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     316:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     31d:	00 
     31e:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     323:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     328:	44 89 f9             	mov    %r15d,%ecx
     32b:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     330:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     335:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     33a:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     33f:	e9 07 ff ff ff       	jmp    0x24b
     344:	4c 89 6c 24 58       	mov    %r13,0x58(%rsp)
     349:	b1 01                	mov    $0x1,%cl
     34b:	89 4c 24 04          	mov    %ecx,0x4(%rsp)
     34f:	4c 89 74 24 40       	mov    %r14,0x40(%rsp)
     354:	31 c9                	xor    %ecx,%ecx
     356:	4c 89 5c 24 50       	mov    %r11,0x50(%rsp)
     35b:	eb 24                	jmp    0x381
     35d:	4d 89 e1             	mov    %r12,%r9
     360:	c7 44 24 04 00 00 00 	movl   $0x0,0x4(%rsp)
     367:	00 
     368:	4c 89 c0             	mov    %r8,%rax
     36b:	48 89 74 24 58       	mov    %rsi,0x58(%rsp)
     370:	4c 89 44 24 40       	mov    %r8,0x40(%rsp)
     375:	48 8b 4c 24 30       	mov    0x30(%rsp),%rcx
     37a:	48 89 4c 24 50       	mov    %rcx,0x50(%rsp)
     37f:	31 c9                	xor    %ecx,%ecx
     381:	31 d2                	xor    %edx,%edx
     383:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     388:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     38d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     392:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     397:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     39c:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     3a1:	08 d1                	or     %dl,%cl
     3a3:	49 01 84 24 c0 00 00 	add    %rax,0xc0(%r12)
     3aa:	00 
     3ab:	89 4c 24 30          	mov    %ecx,0x30(%rsp)
     3af:	f6 c1 01             	test   $0x1,%cl
     3b2:	74 08                	je     0x3bc
     3b4:	49 ff 84 24 c8 00 00 	incq   0xc8(%r12)
     3bb:	00 
     3bc:	48 83 7c 24 40 00    	cmpq   $0x0,0x40(%rsp)
     3c2:	0f 84 29 01 00 00    	je     0x4f1
     3c8:	4d 89 06             	mov    %r8,(%r14)
     3cb:	49 89 76 08          	mov    %rsi,0x8(%r14)
     3cf:	4c 8b 74 24 70       	mov    0x70(%rsp),%r14
     3d4:	4d 89 75 40          	mov    %r14,0x40(%r13)
     3d8:	4c 89 cf             	mov    %r9,%rdi
     3db:	49 89 f4             	mov    %rsi,%r12
     3de:	ff 15 ef 07 00 00    	call   *0x7ef(%rip)        # 0xbd3
     3e4:	48 85 c0             	test   %rax,%rax
     3e7:	0f 84 2f 01 00 00    	je     0x51c
     3ed:	49 89 c7             	mov    %rax,%r15
     3f0:	48 8b 7c 24 58       	mov    0x58(%rsp),%rdi
     3f5:	ff 15 b0 07 00 00    	call   *0x7b0(%rip)        # 0xbab
     3fb:	48 85 c0             	test   %rax,%rax
     3fe:	0f 84 2f 01 00 00    	je     0x533
     404:	48 b9 23 00 00 00 00 	movabs $0x23,%rcx
     40b:	00 00 00 
     40e:	83 e1 0f             	and    $0xf,%ecx
     411:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     416:	49 8b 7c dd 50       	mov    0x50(%r13,%rbx,8),%rdi
     41b:	89 c9                	mov    %ecx,%ecx
     41d:	4d 8b 64 cd 50       	mov    0x50(%r13,%rcx,8),%r12
     422:	41 0f b7 57 06       	movzwl 0x6(%r15),%edx
     427:	83 e2 01             	and    $0x1,%edx
     42a:	4c 09 fa             	or     %r15,%rdx
     42d:	49 89 54 dd 50       	mov    %rdx,0x50(%r13,%rbx,8)
     432:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     436:	83 e2 01             	and    $0x1,%edx
     439:	48 09 c2             	or     %rax,%rdx
     43c:	49 89 54 cd 50       	mov    %rdx,0x50(%r13,%rcx,8)
     441:	40 f6 c7 01          	test   $0x1,%dil
     445:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     44a:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     44f:	75 19                	jne    0x46a
     451:	ff 0f                	decl   (%rdi)
     453:	75 15                	jne    0x46a
     455:	ff 15 30 07 00 00    	call   *0x730(%rip)        # 0xb8b
     45b:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     460:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     465:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     46a:	41 f6 c4 01          	test   $0x1,%r12b
     46e:	48 8b 5c 24 50       	mov    0x50(%rsp),%rbx
     473:	4c 8b 74 24 40       	mov    0x40(%rsp),%r14
     478:	44 8b 7c 24 30       	mov    0x30(%rsp),%r15d
     47d:	75 1e                	jne    0x49d
     47f:	41 ff 0c 24          	decl   (%r12)
     483:	75 18                	jne    0x49d
     485:	4c 89 e7             	mov    %r12,%rdi
     488:	ff 15 fd 06 00 00    	call   *0x6fd(%rip)        # 0xb8b
     48e:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     493:	4c 8b 44 24 08       	mov    0x8(%rsp),%r8
     498:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     49d:	48 8b 44 24 68       	mov    0x68(%rsp),%rax
     4a2:	48 89 58 10          	mov    %rbx,0x10(%rax)
     4a6:	4c 29 70 20          	sub    %r14,0x20(%rax)
     4aa:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     4af:	49 ff 84 24 b0 00 00 	incq   0xb0(%r12)
     4b6:	00 
     4b7:	4d 01 b4 24 b8 00 00 	add    %r14,0xb8(%r12)
     4be:	00 
     4bf:	41 f6 c7 01          	test   $0x1,%r15b
     4c3:	0f 84 ae 00 00 00    	je     0x577
     4c9:	49 ff 84 24 e0 00 00 	incq   0xe0(%r12)
     4d0:	00 
     4d1:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     4d6:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     4db:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     4e0:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     4e5:	74 29                	je     0x510
     4e7:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4ee:	00 
     4ef:	eb 1f                	jmp    0x510
     4f1:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     4f6:	74 08                	je     0x500
     4f8:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     4ff:	00 
     500:	f6 44 24 30 01       	testb  $0x1,0x30(%rsp)
     505:	48 8b 54 24 48       	mov    0x48(%rsp),%rdx
     50a:	0f 84 88 00 00 00    	je     0x598
     510:	4c 89 c7             	mov    %r8,%rdi
     513:	48 83 c4 78          	add    $0x78,%rsp
     517:	e9 4e 04 00 00       	jmp    0x96a
     51c:	4c 89 e6             	mov    %r12,%rsi
     51f:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     524:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     529:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     52e:	e9 49 fd ff ff       	jmp    0x27c
     533:	41 8b 07             	mov    (%r15),%eax
     536:	85 c0                	test   %eax,%eax
     538:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     53d:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     542:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     547:	78 1f                	js     0x568
     549:	ff c8                	dec    %eax
     54b:	41 89 07             	mov    %eax,(%r15)
     54e:	75 18                	jne    0x568
     550:	4c 89 ff             	mov    %r15,%rdi
     553:	ff 15 32 06 00 00    	call   *0x632(%rip)        # 0xb8b
     559:	4c 8b 6c 24 10       	mov    0x10(%rsp),%r13
     55e:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     563:	48 8b 74 24 18       	mov    0x18(%rsp),%rsi
     568:	4c 8b 64 24 28       	mov    0x28(%rsp),%r12
     56d:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     572:	e9 05 fd ff ff       	jmp    0x27c
     577:	49 ff 84 24 d8 00 00 	incq   0xd8(%r12)
     57e:	00 
     57f:	80 7c 24 04 00       	cmpb   $0x0,0x4(%rsp)
     584:	4c 8b 7c 24 20       	mov    0x20(%rsp),%r15
     589:	4c 8b 74 24 38       	mov    0x38(%rsp),%r14
     58e:	74 08                	je     0x598
     590:	49 ff 84 24 d0 00 00 	incq   0xd0(%r12)
     597:	00 
     598:	4c 89 c7             	mov    %r8,%rdi
     59b:	31 d2                	xor    %edx,%edx
     59d:	48 83 c4 78          	add    $0x78,%rsp
     5a1:	48 83 ec 18          	sub    $0x18,%rsp
     5a5:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     5aa:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     5af:	48 89 fb             	mov    %rdi,%rbx
     5b2:	48 89 f8             	mov    %rdi,%rax
     5b5:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     5b9:	48 8b 78 10          	mov    0x10(%rax),%rdi
     5bd:	48 8b 48 18          	mov    0x18(%rax),%rcx
     5c1:	48 01 f9             	add    %rdi,%rcx
     5c4:	48 89 48 10          	mov    %rcx,0x10(%rax)
     5c8:	48 ff 48 20          	decq   0x20(%rax)
     5cc:	ff 15 d9 05 00 00    	call   *0x5d9(%rip)        # 0xbab
     5d2:	48 85 c0             	test   %rax,%rax
     5d5:	74 18                	je     0x5ef
     5d7:	0f b7 50 06          	movzwl 0x6(%rax),%edx
     5db:	83 e2 01             	and    $0x1,%edx
     5de:	48 09 c2             	or     %rax,%rdx
     5e1:	48 89 df             	mov    %rbx,%rdi
     5e4:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5e9:	48 83 c4 18          	add    $0x18,%rsp
     5ed:	eb 21                	jmp    0x610
     5ef:	49 89 1e             	mov    %rbx,(%r14)
     5f2:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     5f7:	49 89 76 08          	mov    %rsi,0x8(%r14)
     5fb:	49 83 c6 10          	add    $0x10,%r14
     5ff:	48 89 df             	mov    %rbx,%rdi
     602:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     607:	48 83 c4 18          	add    $0x18,%rsp
     60b:	e9 de 03 00 00       	jmp    0x9ee
     610:	48 b8 9c 7b cc 1e 57 	movabs $0x7f571ecc7b9c,%rax
     617:	7f 00 00 
     61a:	49 89 45 38          	mov    %rax,0x38(%r13)
     61e:	49 8b 45 68          	mov    0x68(%r13),%rax
     622:	49 89 55 68          	mov    %rdx,0x68(%r13)
     626:	48 89 c2             	mov    %rax,%rdx
     629:	49 89 3e             	mov    %rdi,(%r14)
     62c:	49 89 76 08          	mov    %rsi,0x8(%r14)
     630:	49 83 c6 10          	add    $0x10,%r14
     634:	48 89 d7             	mov    %rdx,%rdi
     637:	4d 89 75 40          	mov    %r14,0x40(%r13)
     63b:	40 f6 c7 01          	test   $0x1,%dil
     63f:	75 0f                	jne    0x650
     641:	ff 0f                	decl   (%rdi)
     643:	75 0b                	jne    0x650
     645:	50                   	push   %rax
     646:	ff 15 3f 05 00 00    	call   *0x53f(%rip)        # 0xb8b
     64c:	48 83 c4 08          	add    $0x8,%rsp
     650:	31 ff                	xor    %edi,%edi
     652:	31 f6                	xor    %esi,%esi
     654:	31 d2                	xor    %edx,%edx
     656:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     65a:	40 f6 c7 01          	test   $0x1,%dil
     65e:	75 02                	jne    0x662
     660:	ff 07                	incl   (%rdi)
     662:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     668:	0f 84 b4 03 00 00    	je     0xa22
     66e:	49 8b 75 68          	mov    0x68(%r13),%rsi
     672:	48 83 ce 01          	or     $0x1,%rsi
     676:	49 8b 55 68          	mov    0x68(%r13),%rdx
     67a:	48 83 ca 01          	or     $0x1,%rdx
     67e:	48 89 d0             	mov    %rdx,%rax
     681:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     685:	48 83 78 10 10       	cmpq   $0x10,0x10(%rax)
     68a:	0f 83 dc 03 00 00    	jae    0xa6c
     690:	49 89 3e             	mov    %rdi,(%r14)
     693:	49 83 c6 08          	add    $0x8,%r14
     697:	48 89 f7             	mov    %rsi,%rdi
     69a:	48 89 d6             	mov    %rdx,%rsi
     69d:	48 83 ec 18          	sub    $0x18,%rsp
     6a1:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     6a6:	48 89 fb             	mov    %rdi,%rbx
     6a9:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     6ad:	48 89 74 24 08       	mov    %rsi,0x8(%rsp)
     6b2:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     6b6:	ff 15 d7 04 00 00    	call   *0x4d7(%rip)        # 0xb93
     6bc:	48 83 f8 01          	cmp    $0x1,%rax
     6c0:	75 16                	jne    0x6d8
     6c2:	48 89 df             	mov    %rbx,%rdi
     6c5:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     6ca:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     6cf:	48 83 c4 18          	add    $0x18,%rsp
     6d3:	e9 c8 03 00 00       	jmp    0xaa0
     6d8:	48 89 c7             	mov    %rax,%rdi
     6db:	48 89 de             	mov    %rbx,%rsi
     6de:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     6e3:	48 83 c4 18          	add    $0x18,%rsp
     6e7:	48 b8 ac 7b cc 1e 57 	movabs $0x7f571ecc7bac,%rax
     6ee:	7f 00 00 
     6f1:	49 89 45 38          	mov    %rax,0x38(%r13)
     6f5:	48 89 fe             	mov    %rdi,%rsi
     6f8:	49 8b 7e f8          	mov    -0x8(%r14),%rdi
     6fc:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     700:	48 83 ec 18          	sub    $0x18,%rsp
     704:	48 89 54 24 10       	mov    %rdx,0x10(%rsp)
     709:	48 89 f0             	mov    %rsi,%rax
     70c:	48 89 fb             	mov    %rdi,%rbx
     70f:	4c 89 3c 24          	mov    %r15,(%rsp)
     713:	48 83 e7 fe          	and    $0xfffffffffffffffe,%rdi
     717:	48 83 e6 fe          	and    $0xfffffffffffffffe,%rsi
     71b:	49 89 1e             	mov    %rbx,(%r14)
     71e:	48 89 44 24 08       	mov    %rax,0x8(%rsp)
     723:	49 89 46 08          	mov    %rax,0x8(%r14)
     727:	4d 8d 7e 10          	lea    0x10(%r14),%r15
     72b:	4d 89 7d 40          	mov    %r15,0x40(%r13)
     72f:	48 b8 0d 00 00 00 00 	movabs $0xd,%rax
     736:	00 00 00 
     739:	0f b7 c0             	movzwl %ax,%eax
     73c:	48 b9 c0 f5 48 4f 4d 	movabs $0x564d4f48f5c0,%rcx
     743:	56 00 00 
     746:	ff 14 c1             	call   *(%rcx,%rax,8)
     749:	48 85 c0             	test   %rax,%rax
     74c:	74 1c                	je     0x76a
     74e:	0f b7 78 06          	movzwl 0x6(%rax),%edi
     752:	83 e7 01             	and    $0x1,%edi
     755:	48 09 c7             	or     %rax,%rdi
     758:	4c 8b 3c 24          	mov    (%rsp),%r15
     75c:	48 89 de             	mov    %rbx,%rsi
     75f:	48 8b 54 24 08       	mov    0x8(%rsp),%rdx
     764:	48 83 c4 18          	add    $0x18,%rsp
     768:	eb 1d                	jmp    0x787
     76a:	4d 89 fe             	mov    %r15,%r14
     76d:	4c 8b 3c 24          	mov    (%rsp),%r15
     771:	48 89 df             	mov    %rbx,%rdi
     774:	48 8b 74 24 08       	mov    0x8(%rsp),%rsi
     779:	48 8b 54 24 10       	mov    0x10(%rsp),%rdx
     77e:	48 83 c4 18          	add    $0x18,%rsp
     782:	e9 49 03 00 00       	jmp    0xad0
     787:	48 89 d3             	mov    %rdx,%rbx
     78a:	f6 c3 01             	test   $0x1,%bl
     78d:	75 52                	jne    0x7e1
     78f:	ff 0b                	decl   (%rbx)
     791:	75 4e                	jne    0x7e1
     793:	48 83 ec 18          	sub    $0x18,%rsp
     797:	48 89 7c 24 08       	mov    %rdi,0x8(%rsp)
     79c:	48 89 74 24 10       	mov    %rsi,0x10(%rsp)
     7a1:	48 b8 30 82 51 4f 4d 	movabs $0x564d4f518230,%rax
     7a8:	56 00 00 
     7ab:	48 8b 00             	mov    (%rax),%rax
     7ae:	48 85 c0             	test   %rax,%rax
     7b1:	74 17                	je     0x7ca
     7b3:	48 b9 38 82 51 4f 4d 	movabs $0x564d4f518238,%rcx
     7ba:	56 00 00 
     7bd:	48 8b 11             	mov    (%rcx),%rdx
     7c0:	48 89 df             	mov    %rbx,%rdi
     7c3:	be 01 00 00 00       	mov    $0x1,%esi
     7c8:	ff d0                	call   *%rax
     7ca:	48 89 df             	mov    %rbx,%rdi
     7cd:	ff 15 e0 03 00 00    	call   *0x3e0(%rip)        # 0xbb3
     7d3:	48 8b 74 24 10       	mov    0x10(%rsp),%rsi
     7d8:	48 8b 7c 24 08       	mov    0x8(%rsp),%rdi
     7dd:	48 83 c4 18          	add    $0x18,%rsp
     7e1:	48 89 da             	mov    %rbx,%rdx
     7e4:	49 89 3e             	mov    %rdi,(%r14)
     7e7:	49 83 c6 08          	add    $0x8,%r14
     7eb:	48 89 f7             	mov    %rsi,%rdi
     7ee:	4d 89 75 40          	mov    %r14,0x40(%r13)
     7f2:	40 f6 c7 01          	test   $0x1,%dil
     7f6:	75 0f                	jne    0x807
     7f8:	ff 0f                	decl   (%rdi)
     7fa:	75 0b                	jne    0x807
     7fc:	50                   	push   %rax
     7fd:	ff 15 88 03 00 00    	call   *0x388(%rip)        # 0xb8b
     803:	48 83 c4 08          	add    $0x8,%rsp
     807:	31 ff                	xor    %edi,%edi
     809:	31 f6                	xor    %esi,%esi
     80b:	31 d2                	xor    %edx,%edx
     80d:	41 80 7c 24 22 00    	cmpb   $0x0,0x22(%r12)
     813:	0f 84 eb 02 00 00    	je     0xb04
     819:	48 b8 b8 7b cc 1e 57 	movabs $0x7f571ecc7bb8,%rax
     820:	7f 00 00 
     823:	49 89 45 38          	mov    %rax,0x38(%r13)
     827:	49 8b 46 f8          	mov    -0x8(%r14),%rax
     82b:	49 83 c6 f8          	add    $0xfffffffffffffff8,%r14
     82f:	49 8b 7d 60          	mov    0x60(%r13),%rdi
     833:	49 89 45 60          	mov    %rax,0x60(%r13)
     837:	4d 89 75 40          	mov    %r14,0x40(%r13)
     83b:	40 f6 c7 01          	test   $0x1,%dil
     83f:	75 0f                	jne    0x850
     841:	ff 0f                	decl   (%rdi)
     843:	75 0b                	jne    0x850
     845:	50                   	push   %rax
     846:	ff 15 3f 03 00 00    	call   *0x33f(%rip)        # 0xb8b
     84c:	48 83 c4 08          	add    $0x8,%rsp
     850:	31 ff                	xor    %edi,%edi
     852:	31 f6                	xor    %esi,%esi
     854:	31 d2                	xor    %edx,%edx
     856:	e9 f1 f7 ff ff       	jmp    0x4c
     85b:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     862:	00 00 00 00 
     866:	4d 89 75 40          	mov    %r14,0x40(%r13)
     86a:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     86f:	75 0e                	jne    0x87f
     871:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     878:	56 00 00 
     87b:	48 8b 00             	mov    (%rax),%rax
     87e:	c3                   	ret
     87f:	49 8b 45 00          	mov    0x0(%r13),%rax
     883:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     887:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     88e:	00 00 00 
     891:	89 c9                	mov    %ecx,%ecx
     893:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     897:	48 05 c8 00 00 00    	add    $0xc8,%rax
     89d:	c3                   	ret
     89e:	49 8b 45 00          	mov    0x0(%r13),%rax
     8a2:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8a6:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     8ad:	00 00 00 
     8b0:	89 c9                	mov    %ecx,%ecx
     8b2:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     8b6:	48 05 c8 00 00 00    	add    $0xc8,%rax
     8bc:	49 89 45 38          	mov    %rax,0x38(%r13)
     8c0:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8c7:	00 00 00 00 
     8cb:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8cf:	31 c0                	xor    %eax,%eax
     8d1:	c3                   	ret
     8d2:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     8d9:	00 00 00 00 
     8dd:	4d 89 75 40          	mov    %r14,0x40(%r13)
     8e1:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     8e6:	75 0e                	jne    0x8f6
     8e8:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     8ef:	56 00 00 
     8f2:	48 8b 00             	mov    (%rax),%rax
     8f5:	c3                   	ret
     8f6:	49 8b 45 00          	mov    0x0(%r13),%rax
     8fa:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     8fe:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     905:	00 00 00 
     908:	89 c9                	mov    %ecx,%ecx
     90a:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     90e:	48 05 c8 00 00 00    	add    $0xc8,%rax
     914:	c3                   	ret
     915:	48 b8 a8 a0 49 8b 4d 	movabs $0x564d8b49a0a8,%rax
     91c:	56 00 00 
     91f:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     926:	48 b8 b0 a0 49 8b 4d 	movabs $0x564d8b49a0b0,%rax
     92d:	56 00 00 
     930:	4c 8b 20             	mov    (%rax),%r12
     933:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     938:	ff e0                	jmp    *%rax
     93a:	48 b8 b8 a0 49 8b 4d 	movabs $0x564d8b49a0b8,%rax
     941:	56 00 00 
     944:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     94b:	49 89 3e             	mov    %rdi,(%r14)
     94e:	49 89 76 08          	mov    %rsi,0x8(%r14)
     952:	49 83 c6 10          	add    $0x10,%r14
     956:	48 b8 c0 a0 49 8b 4d 	movabs $0x564d8b49a0c0,%rax
     95d:	56 00 00 
     960:	4c 8b 20             	mov    (%rax),%r12
     963:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     968:	ff e0                	jmp    *%rax
     96a:	50                   	push   %rax
     96b:	49 89 3e             	mov    %rdi,(%r14)
     96e:	49 89 76 08          	mov    %rsi,0x8(%r14)
     972:	49 83 c6 10          	add    $0x10,%r14
     976:	4d 89 75 40          	mov    %r14,0x40(%r13)
     97a:	4c 89 ff             	mov    %r15,%rdi
     97d:	ff 15 18 02 00 00    	call   *0x218(%rip)        # 0xb9b
     983:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     98a:	00 00 00 00 
     98e:	4d 89 75 40          	mov    %r14,0x40(%r13)
     992:	85 c0                	test   %eax,%eax
     994:	74 04                	je     0x99a
     996:	31 c0                	xor    %eax,%eax
     998:	eb 1e                	jmp    0x9b8
     99a:	49 8b 45 00          	mov    0x0(%r13),%rax
     99e:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     9a2:	48 b9 21 00 00 00 00 	movabs $0x21,%rcx
     9a9:	00 00 00 
     9ac:	89 c9                	mov    %ecx,%ecx
     9ae:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9b2:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9b8:	59                   	pop    %rcx
     9b9:	c3                   	ret
     9ba:	49 8b 45 00          	mov    0x0(%r13),%rax
     9be:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     9c2:	48 b9 1a 00 00 00 00 	movabs $0x1a,%rcx
     9c9:	00 00 00 
     9cc:	89 c9                	mov    %ecx,%ecx
     9ce:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     9d2:	48 05 c8 00 00 00    	add    $0xc8,%rax
     9d8:	49 89 45 38          	mov    %rax,0x38(%r13)
     9dc:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     9e3:	00 00 00 00 
     9e7:	4d 89 75 40          	mov    %r14,0x40(%r13)
     9eb:	31 c0                	xor    %eax,%eax
     9ed:	c3                   	ret
     9ee:	49 8b 45 00          	mov    0x0(%r13),%rax
     9f2:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     9f6:	48 b9 10 00 00 00 00 	movabs $0x10,%rcx
     9fd:	00 00 00 
     a00:	89 c9                	mov    %ecx,%ecx
     a02:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a06:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a0c:	49 89 45 38          	mov    %rax,0x38(%r13)
     a10:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a17:	00 00 00 00 
     a1b:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a1f:	31 c0                	xor    %eax,%eax
     a21:	c3                   	ret
     a22:	49 89 3e             	mov    %rdi,(%r14)
     a25:	49 83 c6 08          	add    $0x8,%r14
     a29:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     a30:	00 00 00 00 
     a34:	4d 89 75 40          	mov    %r14,0x40(%r13)
     a38:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     a3d:	75 0e                	jne    0xa4d
     a3f:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     a46:	56 00 00 
     a49:	48 8b 00             	mov    (%rax),%rax
     a4c:	c3                   	ret
     a4d:	49 8b 45 00          	mov    0x0(%r13),%rax
     a51:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     a55:	48 b9 13 00 00 00 00 	movabs $0x13,%rcx
     a5c:	00 00 00 
     a5f:	89 c9                	mov    %ecx,%ecx
     a61:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     a65:	48 05 c8 00 00 00    	add    $0xc8,%rax
     a6b:	c3                   	ret
     a6c:	48 b8 c8 a0 49 8b 4d 	movabs $0x564d8b49a0c8,%rax
     a73:	56 00 00 
     a76:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     a7d:	49 89 3e             	mov    %rdi,(%r14)
     a80:	49 89 76 08          	mov    %rsi,0x8(%r14)
     a84:	49 89 56 10          	mov    %rdx,0x10(%r14)
     a88:	49 83 c6 18          	add    $0x18,%r14
     a8c:	48 b8 d0 a0 49 8b 4d 	movabs $0x564d8b49a0d0,%rax
     a93:	56 00 00 
     a96:	4c 8b 20             	mov    (%rax),%r12
     a99:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     a9e:	ff e0                	jmp    *%rax
     aa0:	48 b8 d8 a0 49 8b 4d 	movabs $0x564d8b49a0d8,%rax
     aa7:	56 00 00 
     aaa:	49 89 87 38 01 00 00 	mov    %rax,0x138(%r15)
     ab1:	49 89 3e             	mov    %rdi,(%r14)
     ab4:	49 89 76 08          	mov    %rsi,0x8(%r14)
     ab8:	49 83 c6 10          	add    $0x10,%r14
     abc:	48 b8 e0 a0 49 8b 4d 	movabs $0x564d8b49a0e0,%rax
     ac3:	56 00 00 
     ac6:	4c 8b 20             	mov    (%rax),%r12
     ac9:	49 8b 44 24 58       	mov    0x58(%r12),%rax
     ace:	ff e0                	jmp    *%rax
     ad0:	49 8b 45 00          	mov    0x0(%r13),%rax
     ad4:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     ad8:	48 b9 1a 00 00 00 00 	movabs $0x1a,%rcx
     adf:	00 00 00 
     ae2:	89 c9                	mov    %ecx,%ecx
     ae4:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     ae8:	48 05 c8 00 00 00    	add    $0xc8,%rax
     aee:	49 89 45 38          	mov    %rax,0x38(%r13)
     af2:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     af9:	00 00 00 00 
     afd:	4d 89 75 40          	mov    %r14,0x40(%r13)
     b01:	31 c0                	xor    %eax,%eax
     b03:	c3                   	ret
     b04:	49 c7 87 30 01 00 00 	movq   $0x0,0x130(%r15)
     b0b:	00 00 00 00 
     b0f:	4d 89 75 40          	mov    %r14,0x40(%r13)
     b13:	41 80 7d 4a 03       	cmpb   $0x3,0x4a(%r13)
     b18:	75 0e                	jne    0xb28
     b1a:	48 b8 c0 49 4f 4f 4d 	movabs $0x564d4f4f49c0,%rax
     b21:	56 00 00 
     b24:	48 8b 00             	mov    (%rax),%rax
     b27:	c3                   	ret
     b28:	49 8b 45 00          	mov    0x0(%r13),%rax
     b2c:	48 83 e0 fe          	and    $0xfffffffffffffffe,%rax
     b30:	48 b9 20 00 00 00 00 	movabs $0x20,%rcx
     b37:	00 00 00 
     b3a:	89 c9                	mov    %ecx,%ecx
     b3c:	48 8d 04 48          	lea    (%rax,%rcx,2),%rax
     b40:	48 05 c8 00 00 00    	add    $0xc8,%rax
     b46:	c3                   	ret
     b47:	50                   	push   %rax
     b48:	48 bf 63 2b 9d 1e 57 	movabs $0x7f571e9d2b63,%rdi
     b4f:	7f 00 00 
     b52:	48 be 6e 2b 9d 1e 57 	movabs $0x7f571e9d2b6e,%rsi
     b59:	7f 00 00 
     b5c:	ff 15 41 00 00 00    	call   *0x41(%rip)        # 0xba3
     b62:	00 5f 4a             	add    %bl,0x4a(%rdi)
     b65:	49 54                	rex.WB push %r12
     b67:	5f                   	pop    %rdi
     b68:	45                   	rex.RB
     b69:	4e 54                	rex.WRX push %rsp
     b6b:	52                   	push   %rdx
     b6c:	59                   	pop    %rcx
     b6d:	00 46 61             	add    %al,0x61(%rsi)
     b70:	74 61                	je     0xbd3
     b72:	6c                   	insb   (%dx),%es:(%rdi)
     b73:	20 65 72             	and    %ah,0x72(%rbp)
     b76:	72 6f                	jb     0xbe7
     b78:	72 20                	jb     0xb9a
     b7a:	75 6f                	jne    0xbeb
     b7c:	70 20                	jo     0xb9e
     b7e:	65 78 65             	gs js  0xbe6
     b81:	63 75 74             	movsxd 0x74(%rbp),%esi
     b84:	65 64 2e 00 00       	gs fs add %al,%fs:(%rax)
     b89:	00 00                	add    %al,(%rax)
     b8b:	e0 c0                	loopne 0xb4d
     b8d:	00 4f 4d             	add    %cl,0x4d(%rdi)
     b90:	56                   	push   %rsi
     b91:	00 00                	add    %al,(%rax)
     b93:	00 5d fe             	add    %bl,-0x2(%rbp)
     b96:	4e                   	rex.WRX
     b97:	4d 56                	rex.WRB push %r14
     b99:	00 00                	add    %al,(%rax)
     b9b:	e0 ab                	loopne 0xb48
     b9d:	15 4f 4d 56 00       	adc    $0x564d4f,%eax
     ba2:	00 c0                	add    %al,%al
     ba4:	8e 1d 4f 4d 56 00    	mov    0x564d4f(%rip),%ds        # 0x5658f9
     baa:	00 d0                	add    %dl,%al
     bac:	cb                   	lret
     bad:	fd                   	std
     bae:	4e                   	rex.WRX
     baf:	4d 56                	rex.WRB push %r14
     bb1:	00 00                	add    %al,(%rax)
     bb3:	80 0a fd             	orb    $0xfd,(%rdx)
     bb6:	4e                   	rex.WRX
     bb7:	4d 56                	rex.WRB push %r14
     bb9:	00 00                	add    %al,(%rax)
     bbb:	60                   	(bad)
     bbc:	91                   	xchg   %eax,%ecx
     bbd:	1b 4f 4d             	sbb    0x4d(%rdi),%ecx
     bc0:	56                   	push   %rsi
     bc1:	00 00                	add    %al,(%rax)
     bc3:	60                   	(bad)
     bc4:	2b fe                	sub    %esi,%edi
     bc6:	4e                   	rex.WRX
     bc7:	4d 56                	rex.WRB push %r14
     bc9:	00 00                	add    %al,(%rax)
     bcb:	50                   	push   %rax
     bcc:	41                   	rex.B
     bcd:	f2 4e                	repnz rex.WRX
     bcf:	4d 56                	rex.WRB push %r14
     bd1:	00 00                	add    %al,(%rax)
     bd3:	f0 25 fe 4e 4d 56    	lock and $0x564d4efe,%eax
	...
