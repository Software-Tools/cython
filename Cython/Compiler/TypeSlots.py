#
#   Pyrex - Tables describing slots in the type object
#           and associated know-how.
#

import Naming
import PyrexTypes
import StringEncoding
import sys

invisible = ['__cinit__', '__dealloc__', '__richcmp__', 
             '__nonzero__', '__bool__']

class Signature(object):
    #  Method slot signature descriptor.
    #
    #  has_dummy_arg      boolean
    #  has_generic_args   boolean
    #  fixed_arg_format   string
    #  ret_format         string
    #  error_value        string
    #
    #  The formats are strings made up of the following
    #  characters:
    #
    #    'O'  Python object
    #    'T'  Python object of the type of 'self'
    #    'v'  void
    #    'p'  void *
    #    'P'  void **
    #    'i'  int
    #    'b'  bint
    #    'I'  int *
    #    'l'  long
    #    'z'  Py_ssize_t
    #    'Z'  Py_ssize_t *
    #    's'  char *
    #    'S'  char **
    #    'r'  int used only to signal exception
    #    'B'  Py_buffer *
    #    '-'  dummy 'self' argument (not used)
    #    '*'  rest of args passed as generic Python
    #           arg tuple and kw dict (must be last
    #           char in format string)
    
    format_map = {
        'O': PyrexTypes.py_object_type,
        'v': PyrexTypes.c_void_type,
        'p': PyrexTypes.c_void_ptr_type,
        'P': PyrexTypes.c_void_ptr_ptr_type,
        'i': PyrexTypes.c_int_type,
        'b': PyrexTypes.c_bint_type,
        'I': PyrexTypes.c_int_ptr_type,
        'l': PyrexTypes.c_long_type,
        'z': PyrexTypes.c_py_ssize_t_type,
        'Z': PyrexTypes.c_py_ssize_t_ptr_type,
        's': PyrexTypes.c_char_ptr_type,
        'S': PyrexTypes.c_char_ptr_ptr_type,
        'r': PyrexTypes.c_returncode_type,
        'B': PyrexTypes.c_py_buffer_ptr_type,
        # 'T', '-' and '*' are handled otherwise
        # and are not looked up in here
    }
    
    error_value_map = {
        'O': "NULL",
        'i': "-1",
        'b': "-1",
        'l': "-1",
        'r': "-1",
        'z': "-1",
    }
    
    def __init__(self, arg_format, ret_format):
        self.has_dummy_arg = 0
        self.has_generic_args = 0
        if arg_format[:1] == '-':
            self.has_dummy_arg = 1
            arg_format = arg_format[1:]
        if arg_format[-1:] == '*':
            self.has_generic_args = 1
            arg_format = arg_format[:-1]
        self.fixed_arg_format = arg_format
        self.ret_format = ret_format
        self.error_value = self.error_value_map.get(ret_format, None)
    
    def num_fixed_args(self):
        return len(self.fixed_arg_format)
    
    def is_self_arg(self, i):
        # argument is 'self' for methods or 'class' for classmethods
        return self.fixed_arg_format[i] == 'T'
    
    def fixed_arg_type(self, i):
        return self.format_map[self.fixed_arg_format[i]]
    
    def return_type(self):
        return self.format_map[self.ret_format]

    def exception_value(self):
        return self.error_value_map.get(self.ret_format)
    
    def function_type(self):
        #  Construct a C function type descriptor for this signature
        args = []
        for i in xrange(self.num_fixed_args()):
            arg_type = self.fixed_arg_type(i)
            args.append(PyrexTypes.CFuncTypeArg("", arg_type, None))
        ret_type = self.return_type()
        exc_value = self.exception_value()
        return PyrexTypes.CFuncType(ret_type, args, exception_value = exc_value)

    def method_flags(self):
        if self.ret_format == "O":
            full_args = self.fixed_arg_format
            if self.has_dummy_arg:
                full_args = "O" + full_args
            if full_args in ["O", "T"]:
                if self.has_generic_args:
                    return [method_varargs, method_keywords]
                else:
                    return [method_noargs]
            elif full_args in ["OO", "TO"] and not self.has_generic_args:
                return [method_onearg]
        return None


class SlotDescriptor(object):
    #  Abstract base class for type slot descriptors.
    #
    #  slot_name    string           Member name of the slot in the type object
    #  is_initialised_dynamically    Is initialised by code in the module init function
    #  flag                          Py_TPFLAGS_XXX value indicating presence of slot
    #  py3                           Indicates presence of slot in Python 3
    #  py2                           Indicates presence of slot in Python 2
    #  ifdef                         Full #ifdef string that slot is wrapped in. Using this causes py3, py2 and flags to be ignored.)

    def __init__(self, slot_name, dynamic=0,
                 flag=None, py3=True, py2=True, ifdef=None):
        self.slot_name = slot_name
        self.is_initialised_dynamically = dynamic
        self.flag = flag
        self.py3 = py3
        self.py2 = py2
        self.ifdef = ifdef

    def generate(self, scope, code):
        if self.is_initialised_dynamically:
            value = 0
        else:
            value = self.slot_code(scope)
        flag = self.flag
        py3 = self.py3
        py2 = self.py2
        if self.ifdef:
            code.putln("#if %s" % self.ifdef)
        else:
            if not py3:
                code.putln("#if PY_MAJOR_VERSION < 3")
            elif not py2:
                code.putln("#if PY_MAJOR_VERSION >= 3")
            if flag:
                code.putln("#if (PY_MAJOR_VERSION >= 3) || (Py_TPFLAGS_DEFAULT & %s)" % flag)
        if py3 == '<RESERVED>':
            code.putln("#if PY_MAJOR_VERSION >= 3")
            code.putln("0, /*reserved*/")
            code.putln("#else")

        code.putln("%s, /*%s*/" % (value, self.slot_name))
        if py3 == '<RESERVED>':
            code.putln("#endif")
        if flag or (not py3 or not py2) or self.ifdef:
            code.putln("#endif")

    # Some C implementations have trouble statically 
    # initialising a global with a pointer to an extern 
    # function, so we initialise some of the type slots
    # in the module init function instead.

    def generate_dynamic_init_code(self, scope, code):
        if self.is_initialised_dynamically:
            value = self.slot_code(scope)
            if value != "0":
                code.putln("%s.%s = %s;" % (
                    scope.parent_type.typeobj_cname, 
                    self.slot_name, 
                    value
                    )
            )


class FixedSlot(SlotDescriptor):
    #  Descriptor for a type slot with a fixed value.
    #
    #  value        string
    
    def __init__(self, slot_name, value, flag=None, py3=True, py2=True, ifdef=None):
        SlotDescriptor.__init__(self, slot_name, flag=flag, py3=py3, py2=py2, ifdef=ifdef)
        self.value = value
    
    def slot_code(self, scope):
        return self.value


class EmptySlot(FixedSlot):
    #  Descriptor for a type slot whose value is always 0.
    
    def __init__(self, slot_name, flag=None, py3=True, py2=True, ifdef=None):
        FixedSlot.__init__(self, slot_name, "0", flag=flag, py3=py3, py2=py2, ifdef=ifdef)


class MethodSlot(SlotDescriptor):
    #  Type slot descriptor for a user-definable method.
    #
    #  signature    Signature
    #  method_name  string           The __xxx__ name of the method
    #  alternatives [string]         Alternative list of __xxx__ names for the method
    
    def __init__(self, signature, slot_name, method_name, fallback=None, 
                 flag=None, py3=True, py2=True, ifdef=None):
        SlotDescriptor.__init__(self, slot_name, flag=flag, py3=py3, py2=py2, ifdef=ifdef)
        self.signature = signature
        self.slot_name = slot_name
        self.method_name = method_name
        self.alternatives = []
        method_name_to_slot[method_name] = self
        #
        if fallback:
            self.alternatives.append(fallback)
        for alt in (self.py2, self.py3):
            if isinstance(alt, (tuple, list)):
                slot_name, method_name = alt
                self.alternatives.append(method_name)
                method_name_to_slot[method_name] = self

    def slot_code(self, scope):
        entry = scope.lookup_here(self.method_name)
        if entry and entry.func_cname:
            return entry.func_cname
        for method_name in self.alternatives:
            entry = scope.lookup_here(method_name)
            if entry and entry.func_cname:
                return entry.func_cname
        return "0"


class InternalMethodSlot(SlotDescriptor):
    #  Type slot descriptor for a method which is always
    #  synthesized by Cython.
    #
    #  slot_name    string           Member name of the slot in the type object

    def __init__(self, slot_name, **kargs):
        SlotDescriptor.__init__(self, slot_name, **kargs)

    def slot_code(self, scope):
        return scope.mangle_internal(self.slot_name)


class GCDependentSlot(InternalMethodSlot):
    #  Descriptor for a slot whose value depends on whether
    #  the type participates in GC.
    
    def __init__(self, slot_name, **kargs):
        InternalMethodSlot.__init__(self, slot_name, **kargs)
    
    def slot_code(self, scope):
        if not scope.needs_gc():
            return "0"
        if not scope.has_pyobject_attrs:
            # if the type does not have object attributes, it can
            # delegate GC methods to its parent - iff the parent
            # functions are defined in the same module
            parent_type_scope = scope.parent_type.base_type.scope
            if scope.parent_scope is parent_type_scope.parent_scope:
                entry = scope.parent_scope.lookup_here(scope.parent_type.base_type.name)
                if entry.visibility != 'extern':
                    return self.slot_code(parent_type_scope)
        return InternalMethodSlot.slot_code(self, scope)
        
        
class ConstructorSlot(InternalMethodSlot):
    #  Descriptor for tp_new and tp_dealloc.
    
    def __init__(self, slot_name, method, **kargs):
        InternalMethodSlot.__init__(self, slot_name, **kargs)
        self.method = method
    
    def slot_code(self, scope):
        if scope.parent_type.base_type \
            and not scope.has_pyobject_attrs \
            and not scope.lookup_here(self.method):
            # if the type does not have object attributes, it can
            # delegate GC methods to its parent - iff the parent
            # functions are defined in the same module
            parent_type_scope = scope.parent_type.base_type.scope
            if scope.parent_scope is parent_type_scope.parent_scope:
                entry = scope.parent_scope.lookup_here(scope.parent_type.base_type.name)
                if entry.visibility != 'extern':
                    return self.slot_code(parent_type_scope)
        return InternalMethodSlot.slot_code(self, scope)


class SyntheticSlot(InternalMethodSlot):
    #  Type slot descriptor for a synthesized method which
    #  dispatches to one or more user-defined methods depending
    #  on its arguments. If none of the relevant methods are
    #  defined, the method will not be synthesized and an
    #  alternative default value will be placed in the type
    #  slot.
    
    def __init__(self, slot_name, user_methods, default_value, **kargs):
        InternalMethodSlot.__init__(self, slot_name, **kargs)
        self.user_methods = user_methods
        self.default_value = default_value
    
    def slot_code(self, scope):
        if scope.defines_any(self.user_methods):
            return InternalMethodSlot.slot_code(self, scope)
        else:
            return self.default_value


class TypeFlagsSlot(SlotDescriptor):
    #  Descriptor for the type flags slot.
    
    def slot_code(self, scope):
        value = "Py_TPFLAGS_DEFAULT|Py_TPFLAGS_CHECKTYPES|Py_TPFLAGS_BASETYPE|Py_TPFLAGS_HAVE_NEWBUFFER"
        if scope.needs_gc():
            value += "|Py_TPFLAGS_HAVE_GC"
        return value


class DocStringSlot(SlotDescriptor):
    #  Descriptor for the docstring slot.
    
    def slot_code(self, scope):
        if scope.doc is not None:
            if scope.doc.is_unicode:
                doc = scope.doc.utf8encode()
            else:
                doc = scope.doc.byteencode()
            return '__Pyx_DOCSTR("%s")' % StringEncoding.escape_byte_string(doc)
        else:
            return "0"


class SuiteSlot(SlotDescriptor):
    #  Descriptor for a substructure of the type object.
    #
    #  sub_slots   [SlotDescriptor]
    
    def __init__(self, sub_slots, slot_type, slot_name):
        SlotDescriptor.__init__(self, slot_name)
        self.sub_slots = sub_slots
        self.slot_type = slot_type
        substructures.append(self)
    
    def substructure_cname(self, scope):
        return "%s%s_%s" % (Naming.pyrex_prefix, self.slot_name, scope.class_name)
    
    def slot_code(self, scope):
        return "&%s" % self.substructure_cname(scope)
        
    def generate_substructure(self, scope, code):
        code.putln("")
        code.putln(
            "static %s %s = {" % (
                self.slot_type,
                self.substructure_cname(scope)))
        for slot in self.sub_slots:
            slot.generate(scope, code)
        code.putln("};")

substructures = []   # List of all SuiteSlot instances

class MethodTableSlot(SlotDescriptor):
    #  Slot descriptor for the method table.
    
    def slot_code(self, scope):
        return scope.method_table_cname


class MemberTableSlot(SlotDescriptor):
    #  Slot descriptor for the table of Python-accessible attributes.
    
    def slot_code(self, scope):
        return "0"


class GetSetSlot(SlotDescriptor):
    #  Slot descriptor for the table of attribute get & set methods.
    
    def slot_code(self, scope):
        if scope.property_entries:
            return scope.getset_table_cname
        else:
            return "0"


class BaseClassSlot(SlotDescriptor):
    #  Slot descriptor for the base class slot.

    def __init__(self, name):
        SlotDescriptor.__init__(self, name, dynamic = 1)
    
    def generate_dynamic_init_code(self, scope, code):
        base_type = scope.parent_type.base_type
        if base_type:
            code.putln("%s.%s = %s;" % (
                scope.parent_type.typeobj_cname, 
                self.slot_name,
                base_type.typeptr_cname))

    
# The following dictionary maps __xxx__ method names to slot descriptors.

method_name_to_slot = {}

## The following slots are (or could be) initialised with an
## extern function pointer.
#
#slots_initialised_from_extern = (
#    "tp_free",
#)

#------------------------------------------------------------------------------------------
#
#  Utility functions for accessing slot table data structures
#
#------------------------------------------------------------------------------------------

def get_special_method_signature(name):
    #  Given a method name, if it is a special method,
    #  return its signature, else return None.
    slot = method_name_to_slot.get(name)
    if slot:
        return slot.signature
    else:
        return None

def get_property_accessor_signature(name):
    #  Return signature of accessor for an extension type
    #  property, else None.
    return property_accessor_signatures.get(name)
    
def get_base_slot_function(scope, slot):
    #  Returns the function implementing this slot in the baseclass. 
    #  This is useful for enabling the compiler to optimize calls
    #  that recursively climb the class hierarchy. 
    base_type = scope.parent_type.base_type
    if scope.parent_scope is base_type.scope.parent_scope:
        parent_slot = slot.slot_code(base_type.scope)
        if parent_slot != '0':
            entry = scope.parent_scope.lookup_here(scope.parent_type.base_type.name)
            if entry.visibility != 'extern':
                return parent_slot
    return None

#------------------------------------------------------------------------------------------
#
#  Signatures for generic Python functions and methods.
#
#------------------------------------------------------------------------------------------

pyfunction_signature = Signature("-*", "O")
pymethod_signature = Signature("T*", "O")

#------------------------------------------------------------------------------------------
#
#  Signatures for simple Python functions.
#
#------------------------------------------------------------------------------------------

pyfunction_noargs = Signature("-", "O")
pyfunction_onearg = Signature("-O", "O")

#------------------------------------------------------------------------------------------
#
#  Signatures for the various kinds of function that
#  can appear in the type object and its substructures.
#
#------------------------------------------------------------------------------------------

unaryfunc = Signature("T", "O")            # typedef PyObject * (*unaryfunc)(PyObject *);
binaryfunc = Signature("OO", "O")          # typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
ibinaryfunc = Signature("TO", "O")         # typedef PyObject * (*binaryfunc)(PyObject *, PyObject *);
ternaryfunc = Signature("OOO", "O")        # typedef PyObject * (*ternaryfunc)(PyObject *, PyObject *, PyObject *);
iternaryfunc = Signature("TOO", "O")       # typedef PyObject * (*ternaryfunc)(PyObject *, PyObject *, PyObject *);
callfunc = Signature("T*", "O")            # typedef PyObject * (*ternaryfunc)(PyObject *, PyObject *, PyObject *);
inquiry = Signature("T", "i")              # typedef int (*inquiry)(PyObject *);
lenfunc = Signature("T", "z")              # typedef Py_ssize_t (*lenfunc)(PyObject *);

                                           # typedef int (*coercion)(PyObject **, PyObject **);
intargfunc = Signature("Ti", "O")          # typedef PyObject *(*intargfunc)(PyObject *, int);
ssizeargfunc = Signature("Tz", "O")        # typedef PyObject *(*ssizeargfunc)(PyObject *, Py_ssize_t);
intintargfunc = Signature("Tii", "O")      # typedef PyObject *(*intintargfunc)(PyObject *, int, int);
ssizessizeargfunc = Signature("Tzz", "O")  # typedef PyObject *(*ssizessizeargfunc)(PyObject *, Py_ssize_t, Py_ssize_t);
intobjargproc = Signature("TiO", 'r')      # typedef int(*intobjargproc)(PyObject *, int, PyObject *);
ssizeobjargproc = Signature("TzO", 'r')    # typedef int(*ssizeobjargproc)(PyObject *, Py_ssize_t, PyObject *);
intintobjargproc = Signature("TiiO", 'r')  # typedef int(*intintobjargproc)(PyObject *, int, int, PyObject *);
ssizessizeobjargproc = Signature("TzzO", 'r') # typedef int(*ssizessizeobjargproc)(PyObject *, Py_ssize_t, Py_ssize_t, PyObject *);

intintargproc = Signature("Tii", 'r')
ssizessizeargproc = Signature("Tzz", 'r')
objargfunc = Signature("TO", "O")
objobjargproc = Signature("TOO", 'r')      # typedef int (*objobjargproc)(PyObject *, PyObject *, PyObject *);
readbufferproc = Signature("TzP", "z")     # typedef Py_ssize_t (*readbufferproc)(PyObject *, Py_ssize_t, void **);
writebufferproc = Signature("TzP", "z")    # typedef Py_ssize_t (*writebufferproc)(PyObject *, Py_ssize_t, void **);
segcountproc = Signature("TZ", "z")        # typedef Py_ssize_t (*segcountproc)(PyObject *, Py_ssize_t *);
charbufferproc = Signature("TzS", "z")     # typedef Py_ssize_t (*charbufferproc)(PyObject *, Py_ssize_t, char **);
objargproc = Signature("TO", 'r')          # typedef int (*objobjproc)(PyObject *, PyObject *);
                                           # typedef int (*visitproc)(PyObject *, void *);
                                           # typedef int (*traverseproc)(PyObject *, visitproc, void *);

destructor = Signature("T", "v")           # typedef void (*destructor)(PyObject *);
# printfunc = Signature("TFi", 'r')        # typedef int (*printfunc)(PyObject *, FILE *, int);
                                           # typedef PyObject *(*getattrfunc)(PyObject *, char *);
getattrofunc = Signature("TO", "O")        # typedef PyObject *(*getattrofunc)(PyObject *, PyObject *);
                                           # typedef int (*setattrfunc)(PyObject *, char *, PyObject *);
setattrofunc = Signature("TOO", 'r')       # typedef int (*setattrofunc)(PyObject *, PyObject *, PyObject *);
delattrofunc = Signature("TO", 'r')
cmpfunc = Signature("TO", "i")             # typedef int (*cmpfunc)(PyObject *, PyObject *);
reprfunc = Signature("T", "O")             # typedef PyObject *(*reprfunc)(PyObject *);
hashfunc = Signature("T", "l")             # typedef long (*hashfunc)(PyObject *);
                                           # typedef PyObject *(*richcmpfunc) (PyObject *, PyObject *, int);
richcmpfunc = Signature("OOi", "O")        # typedef PyObject *(*richcmpfunc) (PyObject *, PyObject *, int);
getiterfunc = Signature("T", "O")          # typedef PyObject *(*getiterfunc) (PyObject *);
iternextfunc = Signature("T", "O")         # typedef PyObject *(*iternextfunc) (PyObject *);
descrgetfunc = Signature("TOO", "O")       # typedef PyObject *(*descrgetfunc) (PyObject *, PyObject *, PyObject *);
descrsetfunc = Signature("TOO", 'r')       # typedef int (*descrsetfunc) (PyObject *, PyObject *, PyObject *);
descrdelfunc = Signature("TO", 'r')
initproc = Signature("T*", 'r')            # typedef int (*initproc)(PyObject *, PyObject *, PyObject *);
                                           # typedef PyObject *(*newfunc)(struct _typeobject *, PyObject *, PyObject *);
                                           # typedef PyObject *(*allocfunc)(struct _typeobject *, int);

getbufferproc = Signature("TBi", "r")      # typedef int (*getbufferproc)(PyObject *, Py_buffer *, int);
releasebufferproc = Signature("TB", "v")   # typedef void (*releasebufferproc)(PyObject *, Py_buffer *);


#------------------------------------------------------------------------------------------
#
#  Signatures for accessor methods of properties.
#
#------------------------------------------------------------------------------------------

property_accessor_signatures = {
    '__get__': Signature("T", "O"),
    '__set__': Signature("TO", 'r'),
    '__del__': Signature("T", 'r')
}

#------------------------------------------------------------------------------------------
#
#  Descriptor tables for the slots of the various type object
#  substructures, in the order they appear in the structure.
#
#------------------------------------------------------------------------------------------

PyNumberMethods = (
    MethodSlot(binaryfunc, "nb_add", "__add__"),
    MethodSlot(binaryfunc, "nb_subtract", "__sub__"),
    MethodSlot(binaryfunc, "nb_multiply", "__mul__"),
    MethodSlot(binaryfunc, "nb_divide", "__div__", py3 = False),
    MethodSlot(binaryfunc, "nb_remainder", "__mod__"),
    MethodSlot(binaryfunc, "nb_divmod", "__divmod__"),
    MethodSlot(ternaryfunc, "nb_power", "__pow__"),
    MethodSlot(unaryfunc, "nb_negative", "__neg__"),
    MethodSlot(unaryfunc, "nb_positive", "__pos__"),
    MethodSlot(unaryfunc, "nb_absolute", "__abs__"),
    MethodSlot(inquiry, "nb_nonzero", "__nonzero__", py3 = ("nb_bool", "__bool__")),
    MethodSlot(unaryfunc, "nb_invert", "__invert__"),
    MethodSlot(binaryfunc, "nb_lshift", "__lshift__"),
    MethodSlot(binaryfunc, "nb_rshift", "__rshift__"),
    MethodSlot(binaryfunc, "nb_and", "__and__"),
    MethodSlot(binaryfunc, "nb_xor", "__xor__"),
    MethodSlot(binaryfunc, "nb_or", "__or__"),
    EmptySlot("nb_coerce", py3 = False),
    MethodSlot(unaryfunc, "nb_int", "__int__", fallback="__long__"),
    MethodSlot(unaryfunc, "nb_long", "__long__", fallback="__int__", py3 = "<RESERVED>"),
    MethodSlot(unaryfunc, "nb_float", "__float__"),
    MethodSlot(unaryfunc, "nb_oct", "__oct__", py3 = False),
    MethodSlot(unaryfunc, "nb_hex", "__hex__", py3 = False),
    
    # Added in release 2.0
    MethodSlot(ibinaryfunc, "nb_inplace_add", "__iadd__"),
    MethodSlot(ibinaryfunc, "nb_inplace_subtract", "__isub__"),
    MethodSlot(ibinaryfunc, "nb_inplace_multiply", "__imul__"),
    MethodSlot(ibinaryfunc, "nb_inplace_divide", "__idiv__", py3 = False),
    MethodSlot(ibinaryfunc, "nb_inplace_remainder", "__imod__"),
    MethodSlot(ternaryfunc, "nb_inplace_power", "__ipow__"), # NOT iternaryfunc!!!
    MethodSlot(ibinaryfunc, "nb_inplace_lshift", "__ilshift__"),
    MethodSlot(ibinaryfunc, "nb_inplace_rshift", "__irshift__"),
    MethodSlot(ibinaryfunc, "nb_inplace_and", "__iand__"),
    MethodSlot(ibinaryfunc, "nb_inplace_xor", "__ixor__"),
    MethodSlot(ibinaryfunc, "nb_inplace_or", "__ior__"),
    
    # Added in release 2.2
    # The following require the Py_TPFLAGS_HAVE_CLASS flag
    MethodSlot(binaryfunc, "nb_floor_divide", "__floordiv__"),
    MethodSlot(binaryfunc, "nb_true_divide", "__truediv__"),
    MethodSlot(ibinaryfunc, "nb_inplace_floor_divide", "__ifloordiv__"),
    MethodSlot(ibinaryfunc, "nb_inplace_true_divide", "__itruediv__"),

    # Added in release 2.5
    MethodSlot(unaryfunc, "nb_index", "__index__", flag = "Py_TPFLAGS_HAVE_INDEX")
)

PySequenceMethods = (
    MethodSlot(lenfunc, "sq_length", "__len__"),
    EmptySlot("sq_concat"), # nb_add used instead
    EmptySlot("sq_repeat"), # nb_multiply used instead
    SyntheticSlot("sq_item", ["__getitem__"], "0"),    #EmptySlot("sq_item"),   # mp_subscript used instead
    MethodSlot(ssizessizeargfunc, "sq_slice", "__getslice__"),
    EmptySlot("sq_ass_item"), # mp_ass_subscript used instead
    SyntheticSlot("sq_ass_slice", ["__setslice__", "__delslice__"], "0"),
    MethodSlot(cmpfunc, "sq_contains", "__contains__"),
    EmptySlot("sq_inplace_concat"), # nb_inplace_add used instead
    EmptySlot("sq_inplace_repeat"), # nb_inplace_multiply used instead
)

PyMappingMethods = (
    MethodSlot(lenfunc, "mp_length", "__len__"),
    MethodSlot(objargfunc, "mp_subscript", "__getitem__"),
    SyntheticSlot("mp_ass_subscript", ["__setitem__", "__delitem__"], "0"),
)

PyBufferProcs = (
    MethodSlot(readbufferproc, "bf_getreadbuffer", "__getreadbuffer__", py3 = False),
    MethodSlot(writebufferproc, "bf_getwritebuffer", "__getwritebuffer__", py3 = False),
    MethodSlot(segcountproc, "bf_getsegcount", "__getsegcount__", py3 = False),
    MethodSlot(charbufferproc, "bf_getcharbuffer", "__getcharbuffer__", py3 = False),

    MethodSlot(getbufferproc, "bf_getbuffer", "__getbuffer__", ifdef = "PY_VERSION_HEX >= 0x02060000"),
    MethodSlot(releasebufferproc, "bf_releasebuffer", "__releasebuffer__", ifdef = "PY_VERSION_HEX >= 0x02060000")
)

#------------------------------------------------------------------------------------------
#
#  The main slot table. This table contains descriptors for all the
#  top-level type slots, beginning with tp_dealloc, in the order they
#  appear in the type object.
#
#------------------------------------------------------------------------------------------

slot_table = (
    ConstructorSlot("tp_dealloc", '__dealloc__'),
    EmptySlot("tp_print"), #MethodSlot(printfunc, "tp_print", "__print__"),
    EmptySlot("tp_getattr"),
    EmptySlot("tp_setattr"),
    MethodSlot(cmpfunc, "tp_compare", "__cmp__", py3 = '<RESERVED>'),
    MethodSlot(reprfunc, "tp_repr", "__repr__"),
    
    SuiteSlot(PyNumberMethods, "PyNumberMethods", "tp_as_number"),
    SuiteSlot(PySequenceMethods, "PySequenceMethods", "tp_as_sequence"),
    SuiteSlot(PyMappingMethods, "PyMappingMethods", "tp_as_mapping"),

    MethodSlot(hashfunc, "tp_hash", "__hash__"),
    MethodSlot(callfunc, "tp_call", "__call__"),
    MethodSlot(reprfunc, "tp_str", "__str__"),
    
    SyntheticSlot("tp_getattro", ["__getattr__","__getattribute__"], "0"), #"PyObject_GenericGetAttr"),
    SyntheticSlot("tp_setattro", ["__setattr__", "__delattr__"], "0"), #"PyObject_GenericSetAttr"),

    SuiteSlot(PyBufferProcs, "PyBufferProcs", "tp_as_buffer"),
    
    TypeFlagsSlot("tp_flags"),
    DocStringSlot("tp_doc"),

    GCDependentSlot("tp_traverse"),
    GCDependentSlot("tp_clear"),

    # Later -- synthesize a method to split into separate ops?
    MethodSlot(richcmpfunc, "tp_richcompare", "__richcmp__"),

    EmptySlot("tp_weaklistoffset"),

    MethodSlot(getiterfunc, "tp_iter", "__iter__"),
    MethodSlot(iternextfunc, "tp_iternext", "__next__"),

    MethodTableSlot("tp_methods"),
    MemberTableSlot("tp_members"),
    GetSetSlot("tp_getset"),
    
    BaseClassSlot("tp_base"), #EmptySlot("tp_base"),
    EmptySlot("tp_dict"),
    
    SyntheticSlot("tp_descr_get", ["__get__"], "0"),
    SyntheticSlot("tp_descr_set", ["__set__", "__delete__"], "0"),
    
    EmptySlot("tp_dictoffset"),
    
    MethodSlot(initproc, "tp_init", "__init__"),
    EmptySlot("tp_alloc"), #FixedSlot("tp_alloc", "PyType_GenericAlloc"),
    InternalMethodSlot("tp_new"),
    EmptySlot("tp_free"),
    
    EmptySlot("tp_is_gc"),
    EmptySlot("tp_bases"),
    EmptySlot("tp_mro"),
    EmptySlot("tp_cache"),
    EmptySlot("tp_subclasses"),
    EmptySlot("tp_weaklist"),
    EmptySlot("tp_del"),
    EmptySlot("tp_version_tag", ifdef="PY_VERSION_HEX >= 0x02060000"),
)

#------------------------------------------------------------------------------------------
#
#  Descriptors for special methods which don't appear directly
#  in the type object or its substructures. These methods are
#  called from slot functions synthesized by Cython.
#
#------------------------------------------------------------------------------------------

MethodSlot(initproc, "", "__cinit__")
MethodSlot(destructor, "", "__dealloc__")
MethodSlot(objobjargproc, "", "__setitem__")
MethodSlot(objargproc, "", "__delitem__")
MethodSlot(ssizessizeobjargproc, "", "__setslice__")
MethodSlot(ssizessizeargproc, "", "__delslice__")
MethodSlot(getattrofunc, "", "__getattr__")
MethodSlot(setattrofunc, "", "__setattr__")
MethodSlot(delattrofunc, "", "__delattr__")
MethodSlot(descrgetfunc, "", "__get__")
MethodSlot(descrsetfunc, "", "__set__")
MethodSlot(descrdelfunc, "", "__delete__")


# Method flags for python-exposed methods. 

method_noargs   = "METH_NOARGS"
method_onearg   = "METH_O"
method_varargs  = "METH_VARARGS"
method_keywords = "METH_KEYWORDS"
method_coexist  = "METH_COEXIST"
