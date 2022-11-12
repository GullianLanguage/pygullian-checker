from typing import TYPE_CHECKING
from dataclasses import dataclass
import copy

from gullian_parser.lexer import Name
from gullian_parser.parser import Ast, TypeDeclaration, StructDeclaration, FunctionDeclaration, Attribute, Subscript

@dataclass
class Type:
    name: Name
    fields: dict[str, "Type"]
    functions: dict[str, FunctionDeclaration]
    declaration: TypeDeclaration
    module_name: str="global"

    def __repr__(self):
        return f'Type({self.name})'
    
    def import_field(self, name: Name | Attribute):
        type_fields = dict(self.fields)

        if type(name) is Name:
            if name in type_fields:
                return type_fields[name]
            
            raise AttributeError(f"{name.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
        elif type(name) is Attribute:
            if name.left in type_fields:
                return type_fields[name.left].import_field(name.right)
            
        raise AttributeError(f"{name.left.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")

    def import_function(self, name: Name | Attribute):
        type_fields = dict(self.fields)

        if type(name) is Name:
            if name in self.functions:
                return self.functions[name]
            
            raise AttributeError(f"{name.format} is not a function of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
        elif type(name) is Attribute:
            if name.left in type_fields:
                return type_fields[name.left].import_function(name.right)
            
        raise AttributeError(f"{name.left.format} is not a field of type {self.name.format}. at line {name.line}, in module {self.module_name}")
    
    @property
    def format(self):
        return self.name.format
    
    @property
    def line(self):
        return self.name.line

    @classmethod
    def new(cls, name: str | Name, declaration: TypeDeclaration=None):
        if type(name) is str:
            return cls(Name(name), dict(), dict(), declaration)

        return cls(name, dict(), dict(), declaration)

@dataclass
class Typed:
    ast: Ast
    type: Type

    @property
    def line(self):
        return self.ast.line
    
    @property
    def format(self):
        return self.ast.format

@dataclass
class GenericType:
    name: str
    parameters: tuple[str]
    declaration: TypeDeclaration
    functions: dict[Name, FunctionDeclaration]
    module: "Module"

    def apply_generic(self, items: tuple[Type]):
        parameters_items_dict = dict(zip(self.parameters, items))
        declaration = copy.deepcopy(self.declaration)

        def apply(type_hint: Name):
            if type(type_hint) is Subscript:
                return self.module.import_type(Subscript(type_hint.head, tuple(apply(item) for item in type_hint.items)))

            elif type_hint in self.parameters:
                return parameters_items_dict[type_hint]

            return self.module.import_type(type_hint)
        
        declaration.fields = [(field_name, apply(field_hint)) for field_name, field_hint in declaration.fields]

        return Type(self.name, list(declaration.fields), dict(self.functions), declaration, self.module.name)

@dataclass
class GenericFunction:
    parameters: tuple[Name]
    declaration: FunctionDeclaration
    module: "Module"

    def apply_generic(self, items: tuple[Type]):
        from .checker import Checker # this is ridiculous, fix later

        parameters_items_dict = dict(zip(self.parameters, items))
        declaration = copy.deepcopy(self.declaration)

        def apply(type_hint: Name):
            if type(type_hint) is Subscript:
                return self.module.import_type(Subscript(type_hint.head, tuple(apply(item) for item in type_hint.items)))

            elif type_hint in self.parameters:
                return parameters_items_dict[type_hint]
            
            return self.module.import_type(type_hint)
        
        declaration.head.parameters = [(parameter_name, apply(parameter_hint)) for parameter_name, parameter_hint in declaration.head.parameters]
        declaration.head.return_hint = apply(declaration.head.return_hint)
        declaration.head.generic = []

        checker = Checker.new(self.module)

        return checker.check_function_declaration(declaration)

@dataclass
class AssociatedFunction:
    associated_type: Type
    declaration: FunctionDeclaration

    @property
    def head(self):
        return self.declaration.head

@dataclass
class Function:
    declaration: FunctionDeclaration

    @property
    def head(self):
        return self.declaration.head

VOID = Type.new('void')
BOOL = Type.new('bool')
INT = Type.new('int')
FLOAT = Type.new('float')
STR = Type.new('str')
PTR = Type.new('ptr')
FUNCTION = Type.new('function')

BASIC_TYPES = {
    'void': VOID,
    'bool': BOOL,
    'int': INT,
    'float': FLOAT,
    'str': STR,
    'ptr': PTR,
    'function': FUNCTION
}

def new_ptr_for(type_: Type):
    return Type(Subscript(PTR, (type_, )), type_.fields, type_.functions, None, type_.module_name)

@dataclass
class Context:
    module: "Module"
    variables: dict[str, "Type | Module"]
    functions: dict[str, FunctionDeclaration]

    @classmethod
    def new(cls):
        return cls(dict())
    
    def copy(self):
        return type(self)(self.module, dict(self.variables), dict(self.functions))
    
    def import_variable(self, name: Name | Attribute):
        if type(name) is Name:
            if name in self.variables:
                return self.variables[name]
            
            raise AttributeError(f"{name.format} is not a variable of the current scope. at line {name.line}, in module {self.module.name}")
        elif type(name) is Attribute:
            if type(name.left) is Attribute:
                return self.import_variable(name.left).import_field(name.right)

            if name.left in self.variables:
                return self.variables[name.left].import_field(name.right)
            
        raise AttributeError(f"{name.left.format} is not a variable of the current scope. at line {name.line}, in module {self.module.name}")

    def import_function(self, name: Name | Attribute):
        if type(name) is Name:
            if name in self.functions:
                return self.functions[name]
            
            raise AttributeError(f"{name.format} is not a function of the current scope. at line {name.line}, in module {self.module.name}")
        elif type(name) is Attribute:
            if type(name.left) is Attribute:
                return self.import_variable(name.left).import_function(name.right)

            if name.left in self.variables:
                return self.variables[name.left].import_function(name.right)
            
            raise AttributeError(f"{name.left.format} is not an variable of the current scope. at line {name.line}, in module {self.module.name}")
        elif type(name) is Subscript:
            base_function = self.import_function(name.head)

            if type(base_function) is GenericFunction:
                return base_function.apply_generic(name.items)
            
            raise TypeError(f"function '{base_function.head.format}' is not a generic function. at line {name.line}, in module {self.module.name}")

        return self.module.import_function(name)

@dataclass
class Module:
    name: str
    types: dict[str, Type | GenericType]
    functions: dict[str, Function | GenericFunction]
    imports: dict[str, "Module"]

    @classmethod
    def new(cls, name: str):
        return cls(name, dict(), dict(), dict())

    def import_type(self, name: Name | Attribute | Type):
        if type(name) is Type:
            return name
        
        if type(name) is Name:
            if name in BASIC_TYPES:
                return BASIC_TYPES[name]
            
            if name in self.types:
                return self.types[name]
            
            raise NameError(f"{name.format} is not a type of module {self.name}. at line {name.line}, in module {self.name}")
        elif type(name) is Attribute:
            if name.left in self.imports:
                return self.imports[name.left].import_type(name.right)
            
            raise NameError(f'{name.left} is not an import of module {self.name}. at line {name.line}, in module {self.name}')
        elif type(name) is Subscript:
            base_type = self.import_type(name.head)

            if type(base_type) is GenericType:
                return base_type.apply_generic(tuple(self.import_type(item) for item in name.items))
            
            if base_type is PTR:
                if len(name.items) > 1:
                    raise IndexError(f"too many type parameters for {name.format}. expected 1, got {len(name.items)}. at line {name.line}, in module {self.name}")
                
                return new_ptr_for(self.import_type(name.items[0]))
            
            raise TypeError(f"The type {base_type.name.format} is not generic, got {name.format}. at line {name.line}, in module {self.name}")

        raise TypeError(f'{name} must be either Name, or Attribute. got {name}. at line {name.line}, in module {self.name}')
    
    def import_function(self, name: Name | Attribute):
        if type(name) is Name:
            return self.functions[name]
        elif type(name) is Attribute:
            if name.left in self.imports:
                return self.imports[name.left].import_function(name.right)
            elif name.left in self.types:
                return self.types[name.left].import_function(name.right)
            
            raise NameError(f'{name.left.format} is not an import of module {self.name}. at line {name.line}')
        elif type(name) is Subscript:
            base_function = self.import_function(name.head)

            if type(base_function) is GenericFunction:
                return base_function.apply_generic(name.items)
            
            raise TypeError(f"function '{base_function.head.format}' is not a generic function. at line {name.line}, in module {self.name}")
        
        raise TypeError(f'{name.format} must be either Name, or Attribute. got {name}. at line {name.line}, in module {self.name}')