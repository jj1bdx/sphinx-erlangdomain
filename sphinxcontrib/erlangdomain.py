# -*- coding: utf-8 -*-
"""
    sphinxcontrib.erlangdomain
    ~~~~~~~~~~~~~~~~~~~~~~~~~~

    Erlang domain.

    :copyright: Copyright 2007-2010 by SHIBUKAWA Yoshiki
    :license: BSD, see LICENSE for details.
"""

import copy
from distutils.version import LooseVersion, StrictVersion
from pkg_resources import get_distribution
import re
import string
import sys

from docutils import nodes
from docutils.parsers.rst import directives

from sphinx import addnodes
from sphinx.roles import XRefRole
from sphinx.locale import l_, _
from sphinx.directives import ObjectDescription
from sphinx.domains import Domain, ObjType, Index
#from sphinx.util.compat import Directive
from docutils.parsers.rst import Directive
from sphinx.util.nodes import make_refnode
from sphinx.util.docfields import Field, GroupedField, TypedField

# +===+====================+=======+=============+==========+=================+
# | # | directive          | ns(*1)| object_type | decltype | role            |
# +===+====================+=======+=============+==========+=================+
# | 1 | .. callback::      | cb    | callback    | callback | :callback:`...` |
# | 2 | .. clause::        | (*2)  | clause      | (*3)     | (*4)            |
# | 3 | .. function::      | fn    | function    | function | :func:`...`     |
# | 4 | .. macro::         | macro | macro       | macro    | :macro:`...`    |
# | 5 | .. opaque::        | ty    | opaque      | opaque   | :type:`...`     |
# | 6 | .. record::        | rec   | record      | record   | :record:`...`   |
# | 7 | .. type::          | ty    | type        | type     | :type:`...`     |
# +---+--------------------+-------+-------------+----------+-----------------+
# | 8 | .. module::        | (n/a) | module      | (n/a)    | :mod:`...`      |
# | 9 | .. currentmodule:: | (n/a) | (n/a)       | (n/a)    | (n/a)           |
# +===+====================+=======+=============+==========+=================+
#
# (*1) namespace. same grouping as role.
# (*2) decltype of clause is fn or cb. depends on whether its ancestor node
#      is function or callback respectively.
# (*3) decltype of clause is function or callback. depends on whether which its
#      ancestor node is.
# (*4) role of clause is :func:`...` or :callback:`...`. depends on whether
#      which its ancestor node is.


RE_ATOM = re.compile( r'''
    ^
    (?: ([a-z]\w*) | '([-\w.]+)' )
    \Z
    ''', re.VERBOSE)


RE_NAME = re.compile( r'''
    ^
    (?: ([A-Za-z_]\w*) | '([-\w.]+)' )
    \Z
    ''', re.VERBOSE)


RE_SIGNATURE = re.compile( r'''
    ^
    # modname.
    (?:
        (?P<modname> [a-z]\w*|'[-\w.]+')
        \s*
        :
        \s*
    )?

    # sigil and thing name.
    (?P<sigil>[#?])?
    (?P<name> [a-zA-Z_]\w*|'[-\w.]+')
    \s*

    (?:
        (?:
            [/] \s* (?P<arity>\d+) (?:[.][.](?P<arity_max>\d+))? \s*
        |
            [(] \s* (?P<arg_text>.*?) \s* [)] \s*
        )
        (?:
            [@] \s* (?P<flavor> [a-zA-Z_]\w*|'[-\w.]+') \s*
        |
            \[ \s* [@] \s* (?P<implicit_flavor> [a-zA-Z_]\w*|'[-\w.]+') \s* \] \s*
        )?
        (?: when \s* (?P<when_text> .+?) \s* )?
        (?: -> \s* (?P<ret_ann>\S.*?) \s* )?
    |
        [{] \s* (?P<rec_decl>\S.*?)? \s* [}] \s*
    )?

    # drop a terminal period at this time if any.
    [.]?
    \Z
    ''', re.VERBOSE)

RE_PUNCS = re.compile(r'(\[,|[\[\]{}(),])')

RE_FULLNAME = re.compile( r'''
    ^
    # modname.
    (?P<modname> [a-z]\w*|'[-\w.]+')
    :
    (?P<name> [a-zA-Z_]\w*|'[-\w.]+')
    (?:
        [/]
        (?P<arity>\d+)
        (?:[.][.](?P<arity_max>\d+))?
    )?
    \Z
    ''', re.VERBOSE)

RE_DROP_IMPLICIT_FLAVOR = re.compile( r'''
    \s*
    \[ \s* [@] \s* (?P<implicit_flavor> [a-zA-Z_]\w*|'[-\w.]+') \s* \] \s*
    \Z
    ''', re.VERBOSE)


# {{{ compat.
if sys.version_info[0] < 3:
    # python 2.
    def _iteritems(d):
        return d.iteritems()
else:
    # python 3.
    def _iteritems(d):
        return d.items()


_SPHINX_VERSION = LooseVersion(get_distribution('Sphinx').version)

if _SPHINX_VERSION < LooseVersion('1.3'):
    def _ref_context(env):
        return env.temp_data
else:
    def _ref_context(env):
        return env.ref_context

if _SPHINX_VERSION < LooseVersion('1.4'):
    def _indexentry(entrytype, entryname, target, ignored, key):
        return (entrytype, entryname, target, ignored)
else:
    def _indexentry(entrytype, entryname, target, ignored, key):
        return (entrytype, entryname, target, ignored, key)

if _SPHINX_VERSION < LooseVersion('1.6'):
    def _warn(env, fmt, *args, **kwargs):
        msg = fmt % args
        (docname, lineno) = kwargs['location']
        env.warn(docname, msg, lineno)
else:
    from sphinx.util import logging
    logger = logging.getLogger(__name__)
    def _warn(env, fmt, *args, **kwargs):
        logger.warn(fmt, *args, **kwargs)
# }}} compat.


class ErlangObjectContext:
    def __init__(self, objtype, sigdata):
        self.objtype = objtype
        self.sigdata = sigdata

class ErlangSignature:
    @classmethod
    def canon_atom(cls, name):
        return cls.canon_name_(name, RE_ATOM)

    @classmethod
    def canon_name(cls, name):
        return cls.canon_name_(name, RE_NAME)

    @staticmethod
    def canon_name_(name, regexp):
        m = regexp.match(name)
        if not m:
            # invalid.
            raise ValueError
        if m.group(1) is not None:
            # valid short form.
            return name
        m = RE_ATOM.match(m.group(2))
        if m and m.group(1):
            # can be described in short form.
            return m.group(1)
        # valid long form.
        return name

    def __init__(self, nsname, d):
        self.nsname    = nsname
        self.decltype  = None
        self.modname   = d['modname'  ]  # Optional[str]
        self.sigil     = d['sigil'    ]  # Optional[str]
        self.name      = d['name'     ]  # str
        self.flavor    = d['flavor'   ]  # Optional[str]
        self.when_text = d['when_text']  # Optional[str]
        self.arity     = d['arity'    ]  # Optional[int]
        self.arity_max = d['arity_max']  # Optional[int]
        self.arg_text  = d['arg_text' ]  # Optional[str]
        self.ret_ann   = d['ret_ann'  ]  # Optional[str]
        self.rec_decl  = d['rec_decl' ]  # Optional[str]
        self.arg_list  = None
        self.explicit_flavor = None

        if self.modname is not None:
            self.modname = self.canon_atom(self.modname)
        if nsname == 'macro':
            self.name = self.canon_name(self.name)
        else:
            self.name = self.canon_atom(self.name)

        self.explicit_flavor = self.flavor is not None
        if self.flavor is None and d['implicit_flavor'] is not None:
            self.flavor = d['implicit_flavor']
        if self.flavor is not None:
            self.flavor = self.canon_atom(self.flavor)

        # check constraint on sigil.
        if self.sigil:
            if (nsname, self.sigil) not in (('macro', '?'), ('rec', '#')):
                raise ValueError

        # check constraint on arity.
        if self.arity_max is not None:
            if self.arity is not None and self.arity >= self.arity_max:
                raise ValueError

        # check constraint on the body part by nsname.
        if self.arity is not None:
            arg_type = 'arity'
        elif self.arg_text is not None:
            arg_type = 'arglist'
        elif self.rec_decl is not None:
            arg_type = 'record'
        else:
            arg_type = 'none'

        ACCEPTABLE_ARG_TYPES = {
            'cb'   : ['arity', 'arglist', 'none'],
            'fn'   : ['arity', 'arglist', 'none'],
            'macro': ['arity', 'arglist', 'none'],
            'rec'  : ['record', 'none'],
            'ty'   : ['arity', 'arglist', 'none'],
        }
        if arg_type not in ACCEPTABLE_ARG_TYPES[nsname]:
            if arg_type != 'none':
                raise ValueError

        # compute arity.
        if self.arg_text is not None:
            self.arg_list  = list(self._split_arglist(self.arg_text))
            self.arity     = len(list(filter(lambda arg: arg[0] == 'mandatory', self.arg_list)))
            if self.arity == len(self.arg_list):
                self.arity_max = None
            else:
                self.arity_max = len(self.arg_list)

        if self.when_text is not None:
            if self.nsname not in ('cb', 'fn', 'macro', 'ty'):
                raise ValueError

        if self.ret_ann is not None:
            if self.nsname not in ('cb', 'fn', 'macro'):
                raise ValueError

    @staticmethod
    def _split_arglist(arglist_str):
        tmp   = ''
        stack = []
        opt   = False
        for token in RE_PUNCS.split(arglist_str):
            if not token or token.isspace():
                pass
            elif token in ('[', '{', '('):
                tmp += token
                stack.append(token)
            elif token in (']', '}', ')'):
                if not stack:
                    raise ValueError
                if stack.pop() == '[,':
                    if tmp:
                        yield ('optional', tmp.strip())
                        tmp = ''
                else:
                    tmp += token
            elif token == ',' and not stack:
                yield ('mandatory', tmp.strip())
                tmp = ''
            elif token == '[,':
                if opt:
                    yield ('optional', tmp.strip())
                else:
                    yield ('mandatory', tmp.strip())
                tmp = ''
                opt = True
                stack.append(token)
            else:
                tmp += token

        if stack:
            raise ValueError

        tmp = tmp.strip()
        if tmp:
            yield ('mandatory', tmp)


    @classmethod
    def from_text(cls, sig_text, nsname): # (str, nsname) -> ErlangSignature
        m = RE_SIGNATURE.match(sig_text)
        if not m:
            raise ValueError

        d = m.groupdict()
        if d['arity'] is not None:
            d['arity'] = int(d['arity'])
        if d['arity_max'] is not None:
            d['arity_max'] = int(d['arity_max'])

        return cls(nsname, d)


    def to_disp_name(self):
        if self.modname is None:
            modname = ''
        else:
            modname = '%s:' % (self.modname,)

        name = self.local_disp_name_()

        flavor = ''
        if self.flavor is not None:
            flavor = '@%s' % (self.flavor,)

        if self.ret_ann is not None:
            retann = ' -> %s' % (self.ret_ann,)
        else:
            retann = ''

        return modname + name + flavor + retann

    def local_disp_name_(self):
        if self.nsname == 'rec':
            if self.rec_decl is None:
                return '#%s{}' % (self.name,)
            else:
                return '#%s{ %s }' % (self.name, self.rec_decl)
        else:
            if self.nsname == 'macro':
                sigil = '?'
            else:
                sigil = ''
            if self.arity is None:
                return '%s%s'        % (sigil, self.name)
            elif self.arg_text is not None:
                return '%s%s(%s)'    % (sigil, self.name, self.arg_text)
            elif self.arity_max is None:
                return '%s%s/%d'     % (sigil, self.name, self.arity)
            else:
                return '%s%s/%d..%d' % (sigil, self.name, self.arity, self.arity_max)


    def to_desc_name(self):
        if self.nsname == 'rec':
            return '#%s{}' % (self.name,)
        else:
            if self.nsname == 'macro':
                sigil = '?'
            else:
                sigil = ''
            if self.arity is None:
                return '%s%s'        % (sigil, self.name)
            elif self.arg_text is not None:
                return '%s%s'        % (sigil, self.name)
            elif self.arity_max is None:
                return '%s%s/%d'     % (sigil, self.name, self.arity)
            else:
                return '%s%s/%d..%d' % (sigil, self.name, self.arity, self.arity_max)

    def is_arglist_mandatory(self):
        return self.nsname in ['cb', 'fn', 'ty']

    def to_full_name(self):
        return self.to_full_name_('', True)

    def to_full_qualified_name(self):
        if self.nsname == 'macro':
            sigil = '?'
        elif self.nsname == 'rec':
            sigil = '#'
        else:
            # 'cb', 'fn', 'ty'
            sigil = ''
        return self.to_full_name_('', False)

    def to_full_name_(self, sigil, creation):
        if self.arity_max is not None and creation:
            fullname = '%s:%s%s/%d..%d' % (self.modname, sigil, self.name, self.arity, self.arity_max)
        elif self.arity is not None:
            fullname = '%s:%s%s/%d'     % (self.modname, sigil, self.name, self.arity)
        elif self.is_arglist_mandatory() and creation:
            # arglist is mandatory. treat as no arguments.
            fullname = '%s:%s%s/0' % (self.modname, sigil, self.name)
        else:
            fullname = '%s:%s%s'   % (self.modname, sigil, self.name)

        if self.flavor is not None:
            fullname += '@%s' % (self.flavor)
        return fullname

    def mfa(self):
        return (self.modname, self.name, self.arity)

    @staticmethod
    def drop_flavor_from_full_name(fullname):
        return re.compile(r'@.*\Z').sub('', fullname, 1)

class ErlangBaseObject(ObjectDescription):
    """
    Description of a Erlang language object.
    """

    option_spec = {
        'noindex'   : directives.flag,
        'deprecated': directives.flag,
        'module'    : directives.unchanged,
        'flavor'    : directives.unchanged,
    }

    doc_field_types = [
        TypedField('parameter', label=l_('Parameters'),
                   names=('param', 'parameter'),
                   typerolename='type', typenames=('type',)),
        Field('returnvalue', label=l_('Returns'), has_arg=False,
              names=('returns', 'return')),
        Field('returntype', label=l_('Return type'), has_arg=False,
              names=('rtype',)),
        GroupedField('exceptions', label=l_('Raises'), rolename='type',
                     names=('raises', 'raise'),
                     can_collapse=True),
    ]

    NAMESPACE_FROM_OBJTYPE = {
        'callback': 'cb',
        'function': 'fn',
        'macro'   : 'macro',
        'record'  : 'rec',
        'opaque'  : 'ty',
        'type'    : 'ty',
    }

    NAMESPACE_FROM_ROLE = {
        'callback': 'cb',
        'func'    : 'fn',
        'macro'   : 'macro',
        'record'  : 'rec',
        'type'    : 'ty',
    }

    @staticmethod
    def namespace_of(objtype):
        return ErlangObject.NAMESPACE_FROM_OBJTYPE[objtype]

    @staticmethod
    def namespace_of_role(typ):
        return ErlangObject.NAMESPACE_FROM_ROLE[typ]

    def handle_signature(self, sig_text, signode):
        self.erl_sigdata    = None
        self.erl_env_object = None

        self._setup_data(sig_text)
        self._construct_nodes(signode)

        return self.erl_sigdata.to_full_name()

    def _setup_data(self, sig_text):
        if self.objtype == 'clause':
            env_object = _ref_context(self.env)['erl:object']
            decltype   = env_object.objtype
        else:
            env_object = None
            decltype   = self.objtype

        nsname = self.namespace_of(decltype)
        try:
            sigdata = ErlangSignature.from_text(sig_text, nsname)
        except ValueError:
            _warn(self.env,
                'invalid signature for Erlang %s description: %s',
                decltype,
                sig_text,
                location=(self.env.docname, self.lineno))
            raise

        sigdata.decltype = decltype

        if sigdata.modname is None:
            sigdata.modname = self.options.get(
                'module',
                _ref_context(self.env).get('erl:module', 'erlang'))
        elif 'module' not in self.options:
            pass
        elif self.options['module'] == sigdata.modname:
            pass
        else:
            _warn(self.env,
                'duplicate module specifier in signature and option',
                decltype,
                sig_text,
                location=(self.env.docname, self.lineno))

        if 'flavor' in self.options:
            self.options['flavor'] = ErlangSignature.canon_atom(self.options['flavor'])
            if sigdata.flavor is None:
                sigdata.flavor = self.options['flavor']
            elif sigdata.flavor != self.options['flavor']:
                _warn(self.env,
                    'inconsistent flavor, %s in signature and %s in option.',
                    sigdata.flavor,
                    self.options['flavor'],
                    location=(self.env.docname, self.lineno))
                raise ValueError

        if env_object is not None:
            if sigdata.mfa() != env_object.sigdata.mfa():
                _warn(self.env,
                    'inconsistent %s clause, got %s for %s.',
                    env_object.objtype,
                    '%s:%s/%d' % sigdata.mfa(),
                    '%s:%s/%d' % obj_object.sigdata.mfa(),
                    location=(self.env.docname, self.lineno))
                raise ValueError

        self.erl_sigdata    = sigdata
        self.erl_env_object = env_object

    def _construct_nodes(self, signode):
        sigdata    = self.erl_sigdata
        env_object = self.erl_env_object

        # emulate erlang directives, like '-type', '-record', etc.
        if self.objtype not in ('function', 'clause'):
            objtype_part = '-%s' % (self.objtype,)
            signode += addnodes.desc_annotation(objtype_part, objtype_part)
            signode += nodes.inline(' ', ' ')

        modname_part = '%s:' % (sigdata.modname,)
        signode += addnodes.desc_addname(modname_part, modname_part)

        name_part = sigdata.to_desc_name()
        signode += addnodes.desc_name(name_part, name_part)

        if sigdata.arg_list is not None:
            paramlist_node = addnodes.desc_parameterlist()
            signode += paramlist_node
            last_node = paramlist_node
            for (req, txt) in sigdata.arg_list:
                if req == 'mandatory':
                    last_node += addnodes.desc_parameter(txt, txt)
                else:
                    opt = addnodes.desc_optional()
                    opt += addnodes.desc_parameter(txt, txt)
                    last_node += opt
                    last_node = opt

        if sigdata.explicit_flavor:
            flavor_text = ' @%s' % (sigdata.flavor,)
            signode += nodes.inline(flavor_text, flavor_text)

        if sigdata.when_text is not None:
            when_text = ' when %s' % (sigdata.when_text,)
            signode += nodes.emphasis(when_text, when_text)

        if sigdata.ret_ann:
            signode += addnodes.desc_returns(sigdata.ret_ann, sigdata.ret_ann)


    def add_target_and_index(self, fullname, sig_text, signode):
        refname = 'erl.%s.%s' % (self.erl_sigdata.nsname, fullname)
        self._add_target(refname, signode)
        self._add_index(refname, fullname)

    def _add_target(self, refname, signode):
        signode['first'] = (not self.names)
        if refname not in self.state.document.ids:
            signode['names'].append(refname)
            signode['ids'].append(refname)
            refname_2 = ErlangSignature.drop_flavor_from_full_name(refname)
            if refname_2 != refname and refname_2 not in self.state.document.ids:
                signode['names'].append(refname_2)
                signode['ids'].append(refname_2)
            self.state.document.note_explicit_target(signode)

        sigdata = self.erl_sigdata
        objname = '%s:%s' % (sigdata.modname, sigdata.name)
        if sigdata.arity_max is not None:
            arity_range = range(sigdata.arity, sigdata.arity_max + 1)
        elif sigdata.arity is not None:
            arity_range = [sigdata.arity]
        elif sigdata.is_arglist_mandatory():
            # arglist is mandatory. treat as no arguments.
            arity_range = [0]
        else:
            # no arglist portion.
            arity_range = [None]

        oinv = self.env.domaindata['erl']['objects'][sigdata.nsname]
        arities = oinv.setdefault(objname, {})

        deprecated = 'deprecated' in self.options
        for arity in arity_range:
            new_entry = ObjectEntry(self.env.docname, deprecated, sigdata, refname, self.lineno)
            arities.setdefault(arity, {})
            if sigdata.flavor not in arities[arity]:
                # ok. register entry.
                arities[arity][sigdata.flavor] = new_entry

                if None not in arities[arity]:
                    s2 = copy.copy(sigdata)
                    s2.flavor = None
                    e2 = new_entry.copy(s2)
                    e2.refname  = 'erl.%s.%s' % (s2.nsname, s2.to_full_name())
                    arities[arity][None] = e2
                continue

            # ng. warn duplicate.
            prev_entry = arities[arity][sigdata.flavor]

            if arity is None:
                name_tmp = '%s:%s'    % (sigdata.modname, sigdata.name)
            else:
                name_tmp = '%s:%s/%d' % (sigdata.modname, sigdata.name, arity)
            if sigdata.flavor:
                name_tmp += ' {flavor=%s}' % (sigdata.flavor,)
            _warn(self.env,
                'duplicate Erlang %s description of %s, '
                'other instance in %s line %d.',
                sigdata.decltype,
                name_tmp,
                self.env.doc2path(prev_entry.docname),
                prev_entry.lineno,
                location=(self.env.docname, self.lineno))
        if not arities:
            del oinv[objname]

    def _add_index(self, refname, fullname):
        indextext = self._compute_index_text(fullname)
        self.indexnode['entries'].append(_indexentry('single', indextext, refname, fullname, None))


    def _compute_index_text(self, name):
        decltype = self.erl_sigdata.decltype

        if decltype == 'callback':
            return _('%s (Erlang callback function)') % name
        elif decltype == 'function':
            return _('%s (Erlang function)') % name
        elif decltype == 'macro':
            return _('%s (Erlang macro)') % name
        elif decltype == 'opaque':
            return _('%s (Erlang opaque type)') % name
        elif decltype == 'record':
            return _('%s (Erlang record)') % name
        elif decltype == 'type':
            return _('%s (Erlang type)') % name
        else:
            raise ValueError

class ErlangObject(ErlangBaseObject):
    def handle_signature(self, sig_text, signode):
        if 'erl:object' in _ref_context(self.env):
            _warn(self.env,
                'nested directive may cause undefined behavior.',
                location=(self.env.docname, self.lineno))

        return super(ErlangObject, self).handle_signature(sig_text, signode)


    def before_content(self):
        _ref_context(self.env)['erl:object'] = ErlangObjectContext(self.objtype, self.erl_sigdata)

    def after_content(self):
        if 'erl:object' in _ref_context(self.env):
            del _ref_context(self.env)['erl:object']



class ErlangClauseObject(ErlangBaseObject):
    """
    Description of a Erlang function clause object.
    """

    def _is_valid_location(self):
        if 'erl:object' not in _ref_context(self.env):
            return False
        if _ref_context(self.env)['erl:object'].objtype not in ('function', 'callback'):
            return False

        return True

    def handle_signature(self, sig_text, signode):
        if not self._is_valid_location():
            _warn(self.env,
                'clause directive must be a descendant of function or callback.',
                location=(self.env.docname, self.lineno))
            raise ValueError

        return  super(ErlangClauseObject, self).handle_signature(sig_text, signode)


class ErlangModule(Directive):
    """
    Directive to mark description of a new module.
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {
        'platform'  : directives.unchanged,
        'synopsis'  : directives.unchanged,
        'noindex'   : directives.flag,
        'deprecated': directives.flag,
    }

    def run(self):
        self.env = self.state.document.settings.env
        modname = self.arguments[0].strip()

        try:
            modname = ErlangSignature.canon_atom(modname)
            modname_error = False
        except ValueError:
            _warn(self.env,
                'invalid Erlang module name: %s',
                modname,
                location=(self.env.docname, self.lineno))
            modname = "'invalid-module-name'"
            modname_error = True

        _ref_context(self.env)['erl:module'] = modname

        if 'noindex' in self.options:
            return []

        targetnode = nodes.target('', '', ids=['module-' + modname], ismod=True)
        self.state.document.note_explicit_target(targetnode)

        if not modname_error:
            minv = self.env.domaindata['erl']['modules']
            if modname not in minv:
                minv[modname] = (
                    self.env.docname,
                    self.options.get('synopsis', ''),
                    self.options.get('platform', ''),
                    'deprecated' in self.options)
            else:
                _warn(self.env,
                    'duplicate Erlang module name of %s, other instance in %s.',
                    modname,
                    self.env.doc2path(minv[modname][0]),
                    location=(self.env.docname, self.lineno))

        # the synopsis isn't printed; in fact, it is only used in the
        # modindex currently
        indextext = _('%s (Erlang module)') % modname
        inode = addnodes.index(entries=[_indexentry('single', indextext,
                                             'module-' + modname, modname, None)])
        return [targetnode, inode]


class ErlangCurrentModule(Directive):
    """
    This directive is just to tell Sphinx that we're documenting
    stuff in module foo, but links to module foo won't lead here.
    """

    has_content = False
    required_arguments = 1
    optional_arguments = 0
    final_argument_whitespace = False
    option_spec = {}

    def run(self):
        env = self.state.document.settings.env
        modname = self.arguments[0].strip()
        if modname == 'None':
            _ref_context(env)['erl:module'] = None
        else:
            _ref_context(env)['erl:module'] = modname
        return []


class ErlangXRefRole(XRefRole):
    def process_link(self, env, refnode, has_explicit_title, title, target):
        refnode['erl:module'] = _ref_context(env).get('erl:module')
        if not has_explicit_title:
            title = title.lstrip(':')   # only has a meaning for the target
            target = target.lstrip('~') # only has a meaning for the title
            # if the first character is a tilde, don't display the module/class
            # parts of the contents
            if title[0:1] == '~':
                title = title[1:]
                colon = title.rfind(':')
                if colon != -1:
                    title = title[colon+1:]
        title = RE_DROP_IMPLICIT_FLAVOR.sub('', title)
        return title, target


class ErlangModuleIndex(Index):
    """
    Index subclass to provide the Erlang module index.
    """

    name = 'modindex'
    localname = l_('Erlang Module Index')
    shortname = l_('modules')

    def generate(self, docnames=None):
        content = {}
        # list of prefixes to ignore
        ignores = self.domain.env.config['modindex_common_prefix']
        ignores = sorted(ignores, key=len, reverse=True)
        # list of all modules, sorted by module name
        modules = sorted(_iteritems(self.domain.data['modules']),
                         key=lambda x: x[0].lower())
        # sort out collapsable modules
        prev_modname = ''
        num_toplevels = 0
        for modname, (docname, synopsis, platforms, deprecated) in modules:
            if docnames and docname not in docnames:
                continue

            for ignore in ignores:
                if modname.startswith(ignore):
                    modname = modname[len(ignore):]
                    stripped = ignore
                    break
            else:
                stripped = ''

            # we stripped the whole module name?
            if not modname:
                modname, stripped = stripped, ''

            entries = content.setdefault(modname[0].lower(), [])

            package = modname.split(':', 1)[0]
            if package != modname:
                # it's a submodule
                if prev_modname == package:
                    # first submodule - make parent a group head
                    entries[-1][1] = 1
                elif not prev_modname.startswith(package):
                    # submodule without parent in list, add dummy entry
                    entries.append([stripped + package, 1, '', '', '', '', ''])
                subtype = 2
            else:
                num_toplevels += 1
                subtype = 0

            qualifier = deprecated and _('Deprecated') or ''
            entries.append([stripped + modname, subtype, docname,
                            'module-' + stripped + modname, platforms,
                            qualifier, synopsis])
            prev_modname = modname

        # apply heuristics when to collapse modindex at page load:
        # only collapse if number of toplevel modules is larger than
        # number of submodules
        collapse = len(modules) - num_toplevels < num_toplevels

        # sort by first letter
        content = sorted(_iteritems(content))

        return content, collapse

class ObjectEntry:
    def __init__(self, docname, deprecated, sigdata, refname, lineno):
        self.docname    = docname
        self.deprecated = deprecated
        self.sigdata    = sigdata
        self.refname    = refname
        self.lineno     = lineno

        self.dispname = sigdata.to_disp_name()
        if deprecated:
            self.dispname += ' (deprecated)'

        self.objtype  = sigdata.decltype

    def copy(self, sigdata):
        return ObjectEntry(
                self.docname,
                self.deprecated,
                sigdata,
                self.refname,
                self.lineno,
            )

    def intersphinx_names(self, arity, flavor):
        # Create canoninal and variation names.
        # Sphinx 1.6 does not need variations by
        # Domain.get_full_qualified_name.
        # variations are needed to be referenced by sphinx 1.5 and prior.

        if self.objtype == 'macro':
            sigil_variants = ['', '?']
        elif self.objtype == 'record':
            sigil_variants = ['', '#']
        else:
            sigil_variants = ['']

        if self.objtype == 'record':
            arg_variants = ['', '{}']
        elif arity is None:
            arg_variants = ['']
        elif arity == 0:
            arg_variants = ['/0', '()', ]
        elif self.sigdata.arg_list is None:
            arg_variants = ['/%s' % (arity, )]
        else:
            arg_names = map(lambda pair: pair[1], self.sigdata.arg_list[0:arity])
            arg_variants = [
                '/%s'  % (arity, ),
                '(%s)' % (', '.join(arg_names), ),
            ]

        if self.sigdata.flavor is None:
            flavor_variants = ['']
        else:
            flavor_variants = ['', '@%s' % (flavor, )]

        for sigil in sigil_variants:
            for arg in arg_variants:
                for flavor in flavor_variants:
                    invname = ''.join([
                        self.sigdata.modname,
                        ':',
                        sigil,
                        self.sigdata.name,
                        arg,
                        flavor
                    ])
                    yield invname

    def to_intersphinx_target(self, fullname):
        # '1' means default search priority.
        # See sphinx.domains.Domain#get_objects.
        return (fullname, fullname, self.objtype, self.docname, self.refname, 1)


class ErlangDomain(Domain):
    """Erlang language domain."""
    name = 'erl'
    label = 'Erlang'

    # object_type is used for objtype of result from get_objects.
    object_types = {
        'callback': ObjType(l_('callback function'), 'callback'),
        'function': ObjType(l_('function'),          'func'    ),
        'macro'   : ObjType(l_('macro'),             'macro'   ),
        'opaque'  : ObjType(l_('opaque type'),       'type'    ),
        'record'  : ObjType(l_('record'),            'record'  ),
        'type'    : ObjType(l_('type'),              'type'    ),
        'module'  : ObjType(l_('module'),            'mod'     ),
    }

    # directive name is used for directive#objtype.
    directives = {
        'callback'     : ErlangObject,
        'clause'       : ErlangClauseObject,
        'function'     : ErlangObject,
        'macro'        : ErlangObject,
        'opaque'       : ErlangObject,
        'record'       : ErlangObject,
        'type'         : ErlangObject,
        'module'       : ErlangModule,
        'currentmodule': ErlangCurrentModule,
    }

    roles = {
        'callback': ErlangXRefRole(),
        'func'    : ErlangXRefRole(),
        'macro'   : ErlangXRefRole(),
        'record'  : ErlangXRefRole(),
        'type'    : ErlangXRefRole(),
        'mod'     : ErlangXRefRole(),
    }
    initial_data = {
        'objects'   : {
            # :: namespace -> modfuncname -> arity -> flavor -> ObjectEntry
            # arity maybe None for receords and macros.
            'cb'    : {},
            'fn'    : {},
            'macro' : {},
            'rec'   : {},
            'ty'    : {},
        },
        'modules'   : {}, # modname -> docname, synopsis, platform, deprecated
    }
    data_version = 2
    indices = [
        ErlangModuleIndex,
    ]

    def clear_doc(self, docname):
        rmmods = []
        for modname in self.data['modules']:
            if self.data['modules'][modname][0] == docname:
                rmmods.append(modname)
        for modname in rmmods:
            del self.data['modules'][modname]

        for nsname, oinv in _iteritems(self.data['objects']):
            rmfuncs = []
            for objname, arities in _iteritems(oinv):
                rmarities = []
                for arity, flavors in _iteritems(arities):
                    rmflavors = []
                    for flavor, entry in _iteritems(flavors):
                        if entry.docname == docname:
                            rmflavors.append(flavor)
                    for flavor in rmflavors:
                        del oinv[objname][arity][flavor]
                    if not oinv[objname][arity]:
                        rmarities.append(arity)
                for arity in rmarities:
                    del oinv[objname][arity]
                if not oinv[objname]:
                    rmarities.append(objname)
            for objname in rmfuncs:
                del oinv[objname]

    def _find_obj(self, env, env_modname, name, typ, searchorder=0):
        """
        Find an object for "name", perhaps using the given module name.
        """

        nsname  = ErlangObject.namespace_of_role(typ)
        try:
            sigdata = ErlangSignature.from_text(name, nsname)
        except ValueError:
            return None

        if sigdata.modname is None:
            modname = env_modname
        else:
            modname = sigdata.modname
        objname = '%s:%s' % (modname, sigdata.name)

        oinv = self.data['objects'][nsname]
        if objname not in oinv:
            return None

        if sigdata.arity in oinv[objname]:
            flavors = oinv[objname][sigdata.arity]
        elif sigdata.arity is None:
            arity   = min(oinv[objname])
            flavors = oinv[objname][arity]
        else:
            return None

        if sigdata.flavor not in flavors:
            return None
        else:
            entry = flavors[sigdata.flavor]

        if entry.objtype == 'callback':
            title = '%s (%s)' % (entry.dispname, l_('callback function'))
        elif entry.objtype == 'function':
            title = entry.dispname
        elif entry.objtype == 'macro':
            title = entry.dispname
        elif entry.objtype == 'record':
            title = entry.dispname
        elif entry.objtype == 'opaque':
            title = '%s %s' % (entry.dispname, l_('opaque type'))
        elif entry.objtype == 'type':
            title = '%s %s' % (entry.dispname, l_('type'))
        else:
            raise ValueError

        return title, entry.docname, entry.refname

    def resolve_xref(self, env, fromdocname, builder,
                     typ, target, node, contnode):
        if typ == 'mod':
            if target not in self.data['modules']:
                return None
            docname, synopsis, platform, deprecated = self.data['modules'][target]
            title = target
            if synopsis:
                title += ': ' + synopsis
            if deprecated:
                title += _(' (deprecated)')
            if platform:
                title += ' (' + platform + ')'
            refname = 'module-' + target
            return make_refnode(builder, fromdocname, docname, refname,
                                contnode, title)
        else:
            env_modname = node.get('erl:module')
            searchorder = node.hasattr('refspecific') and 1 or 0
            found = self._find_obj(env, env_modname, target, typ, searchorder)
            if found is None:
                return None
            else:
                title, docname, refname = found
                return make_refnode(builder, fromdocname, docname, refname,
                                    contnode, title)

    def get_objects(self):
        for modname, info in _iteritems(self.data['modules']):
            yield (modname, modname, 'module', info[0], 'module-' + modname, 0)

        for nsname, oinv in _iteritems(self.data['objects']):
            for objname, arities in _iteritems(oinv):
                for arity, flavors in _iteritems(arities):
                    for flavor, entry in _iteritems(flavors):
                        for objname in entry.intersphinx_names(arity, flavor):
                            yield entry.to_intersphinx_target(objname)

    # since sphinx 1.6.
    def get_full_qualified_name(self, node):
        # type: (nodes.Node) -> unicode

        sig_text = node['reftarget']
        nsname   = ErlangObject.namespace_of_role(node['reftype'])
        try:
            sig_data = ErlangSignature.from_text(sig_text, nsname)
        except ValueError:
            return None
        return sig_data.to_full_qualified_name()


def setup(app):
    app.add_domain(ErlangDomain)
