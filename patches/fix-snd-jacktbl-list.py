#!/usr/bin/env python3
"""Port davidjo/snd_hda_macbookpro (patch_cirrus/cirrus_apple.h) to the newer
HDA jack table layout.

Newer kernels replaced `struct snd_array jacktbl` (.list/.used) with a singly
linked list: `struct hda_jack_tbl *jacktbl, *jacktbl_last; int jacktbl_used;`
and entries linked through `->next`. Seen as build errors like
  "'codec->jacktbl' is a pointer; did you mean to use '->'?"

Usage:  python3 -I fix-snd-jacktbl-list.py /path/to/snd_hda_macbookpro
Idempotent. Keeps patch_cirrus/cirrus_apple.h.prelist as a backup.

Which layout is used is chosen at compile time: HDA_JACKTBL_LIST=1 for kernels
>= 7.3.5 (7.3.4 had the array, 7.3.6 has the list; 7.3.5 is a guess). Force it
with -DHDA_JACKTBL_LIST=0 or =1 if the cutoff is wrong for your kernel.
Only the >= 6.17 file (cirrus_apple.h) is patched, not patch_cirrus_apple.h.
"""
import os, re, shutil, sys

root = sys.argv[1] if len(sys.argv) > 1 else '.'
p = os.path.join(root, 'patch_cirrus', 'cirrus_apple.h')
s = open(p).read()

if 'HDA_JACKTBL_LIST' in s:
    print('already applied')
    sys.exit(0)

def sub_once(pattern, repl, text, flags=0):
    new, n = re.subn(pattern, lambda m: repl, text, count=1, flags=flags)
    assert n == 1, 'pattern not found exactly once: ' + pattern
    return new

# 1. cs8409_any_jack_tbl_get_from_nid(): walk the list / array via a macro
s = sub_once(
    r'cs8409_any_jack_tbl_get_from_nid\(struct hda_codec \*codec, hda_nid_t nid\)\s*\n\{.*?\n\}\n',
    '''cs8409_any_jack_tbl_get_from_nid(struct hda_codec *codec, hda_nid_t nid)
{
	struct hda_jack_tbl *jack;
	int i __maybe_unused;

	if (!nid)
		return NULL;
	cs8409_jack_for_each(codec, jack, i)
		if (jack->nid == nid)
			return jack;
	return NULL;
}
''', s, re.S)

# 2. cs_8409_hda_jack_tbl_new(): allocate and link the entry like the kernel does
s = sub_once(
    r'jack = snd_array_new\(&codec->jacktbl\);',
    '''#if HDA_JACKTBL_LIST
	jack = kzalloc(sizeof(*jack), GFP_KERNEL);
	if (jack) {
		if (!codec->jacktbl)
			codec->jacktbl = jack;
		else
			codec->jacktbl_last->next = jack;
		codec->jacktbl_last = jack;
		codec->jacktbl_used++;
	}
#else
	jack = snd_array_new(&codec->jacktbl);
#endif''', s)

# 3. cs_8409_dump_callback(): remaining array walk
s = sub_once(
    r'struct hda_jack_tbl \*jack = codec->jacktbl\.list;',
    'struct hda_jack_tbl *jack;', s)
s = sub_once(
    r'for \(i = 0; i < codec->jacktbl\.used; i\+\+, jack\+\+\) \{',
    'cs8409_jack_for_each(codec, jack, i) {', s)

# 4. every other use is the element count (tag assignment, debug prints)
s, n = re.subn(r'codec->jacktbl\.used', 'cs8409_jack_count(codec)', s)
assert n >= 1, 'no jacktbl.used uses found'

# 5. macro block, inserted before the first copied jack routine
marker = '// another copied routine as this is local to hda_jack.c'
assert marker in s, 'insertion marker not found'
block = '''/* Jack table layout: newer kernels use a linked list instead of snd_array.
 * Force with -DHDA_JACKTBL_LIST=0/1 if the version cutoff is wrong. */
#ifndef HDA_JACKTBL_LIST
#if LINUX_VERSION_CODE >= KERNEL_VERSION(7, 3, 5)
#define HDA_JACKTBL_LIST 1
#else
#define HDA_JACKTBL_LIST 0
#endif
#endif

#if HDA_JACKTBL_LIST
#define cs8409_jack_count(codec)	((codec)->jacktbl_used)
#define cs8409_jack_for_each(codec, jack, i) \\
	for ((i) = 0, (jack) = (codec)->jacktbl; (jack); (jack) = (jack)->next, (i)++)
#else
#define cs8409_jack_count(codec)	((codec)->jacktbl.used)
#define cs8409_jack_for_each(codec, jack, i) \\
	for ((i) = 0, (jack) = (codec)->jacktbl.list; \\
	     (i) < (codec)->jacktbl.used; (i)++, (jack)++)
#endif

'''
s = s.replace(marker, block + marker, 1)

assert 'jacktbl.list' not in s.replace('(codec)->jacktbl.list', '')
assert not re.search(r'codec->jacktbl\.(list|used)', s)
if not os.path.exists(p + '.prelist'):
    shutil.copy(p, p + '.prelist')
open(p, 'w').write(s)
print('applied')
