from dataclasses import dataclass
import os

from gullian_parser.source import Source
from gullian_parser.lexer import *
from gullian_parser.parser import *

from .module import *

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
    
@dataclass
class Checker:
    module: Module
    context: Context
    
    def check_type_compatibility(self, left: Type, right: Type, *, swap_order=True):
        if type(left) is not Type:
            raise TypeError(f"left must be a Type, got {left}. at line {left.line}, in module {self.module.name}")
        elif type(right) is not Type:
            raise TypeError(f"right must be a Type, got {left}. at line {left.line}, in module {self.module.name}")
        
        if left == right:
            return True

        if left is PTR:
            if right is INT:
                return True
            elif right is STR:
                return True
        
        if swap_order:
            return self.check_type_compatibility(right, left, swap_order=False)
        
        return False

    def check_struct_literal(self, struct_literal: StructLiteral):
        type_ =  self.module.import_type(struct_literal.name)

        struct_literal.arguments = [self.check_expression(argument) for argument in struct_literal.arguments]

        if len(struct_literal.arguments) > len(type_.fields):
            raise IndexError(f"too many fields to struct literal '{struct_literal.format}', expected {len(type_.fields)}, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
        elif len(struct_literal.arguments) < len(type_.fields):
            raise IndexError(f"too few fields to struct literal '{struct_literal.format}', expected {len(type_.fields)}, got {len(struct_literal.arguments)}. at line {struct_literal.line}, in module {self.module.name}")
        
        for argument, (field_name, field_type) in zip(struct_literal.arguments, type_.fields):
            if not self.check_type_compatibility(argument.type, field_type):
                raise NameError(f"type mismatch. struct literal parameter '{field_name.format}' expects {field_type.format}, got {argument.type.format}. at line {argument.line}, in module {self.module.name}")

        return Typed(struct_literal, type_)

    def check_call(self, call: Call):
        function = self.context.import_function(call.name)

        if type(function) is AssociatedFunction:
            if type(call.name) is Attribute:
                call.arguments.insert(0, call.name.left)

        if len(call.arguments) > len(function.declaration.head.parameters):
            raise IndexError(f"too many arguments to function '{call.format}', expected {len(function.declaration.head.parameters)}, got {len(call.arguments)}. at line {call.line}, in module {self.module.name}")
        elif len(call.arguments) < len(function.declaration.head.parameters):
            raise IndexError(f"too few arguments to function '{call.format}', expected {len(function.declaration.head.parameters)}, got {len(call.arguments)}. at line {call.line}, in module {self.module.name}")
        
        call.arguments = [self.check_expression(argument) for argument in call.arguments]

        for argument, (parameter_name, parameter_type) in zip(call.arguments, function.head.parameters):
            if not self.check_type_compatibility(argument.type, parameter_type):
                raise NameError(f"type mismatch. parameter '{parameter_name.format}' expects {parameter_type.format}, got {argument.type.format}. at line {argument.line}, in module {self.module.name}")

        return Typed(call, function.declaration. head.return_hint)
    
    # NOTE: May cause issues, it only works for variables
    def check_attribute(self, attribute: Attribute):
        variable_type = self.context.import_variable(attribute.left)
        variable_type_fields = dict(variable_type.fields)

        if attribute.right not in variable_type_fields:
            raise NameError(f'{attribute.right.format} is not a field of type {variable_type.name.format}, at line {attribute.line}, in module {self.module.name}')

        return Typed(attribute, variable_type_fields[attribute.right])
    
    def check_unary_operator(self, unary_operator: UnaryOperator):
        unary_operator.expression = self.check_expression(unary_operator.expression)

        if unary_operator.operator.kind is TokenKind.Ampersand:
            return Typed(unary_operator, PTR)

        raise NotImplementedError(f"bug(checker): checking for unary operator {unary_operator.format} is not implemented yet. at line {unary_operator.line}, in module {self.module.name}")

    def check_expression(self, expression: Expression):
        if type(expression) is Literal:
            if type(expression.value) is str:
                return Typed(expression, STR)
            elif type(expression.value) is int:
                return Typed(expression, INT)
            elif type(expression.value) is float:
                return Typed(expression, FLOAT)

            raise NotImplementedError(f'checker(bug): checking for literal {expression.format} is not implemented yet. at line {expression.line}, in module {self.module.name}')

        if type(expression) is Name:
            if expression in self.context.variables:
                return self.context.variables[expression]
            
            raise NameError(f"{expression.format} is not a variable. at line {expression.line}, in module {self.module.name}")
        elif type(expression) is Attribute:
            return self.check_attribute(expression)
        elif type(expression) is StructLiteral:
            return self.check_struct_literal(expression)
        elif type(expression) is Call:
            return self.check_call(expression)
        elif type(expression) is UnaryOperator:
            return self.check_unary_operator(expression)
        
        raise NotImplementedError(f"bug(checker): checking for {expression.format} is not implemented yet. at line {expression.line}, in module {self.module.name}")
    
    def check_variable_declaration(self, variable_declaration: VariableDeclaration):
        variable_declaration.value = self.check_expression(variable_declaration.value)
        self.context.variables[variable_declaration.name.format] = variable_declaration.value.type

        return variable_declaration

    def check_body(self, body: Body):
        def check(ast: Ast):
            if type(ast) is VariableDeclaration:
                return self.check_variable_declaration(ast)
            elif type(ast) is Call:
                return self.check_call(ast)
            
            raise NotImplementedError(f"bug(checker): checking for {ast.format} is not implemented yet. at line {ast.line}, in module {self.module.name}")

        body.lines = [check(line) for line in body.lines]

        return body
    
    def check_import(self, import_: Import):
        filepath = import_.module_name.format.replace('.', os.sep) + '.gullian'

        if not os.path.exists(filepath):
            raise ImportError(f"can't import '{import_.module_name.format}', file '{filepath}' does not exists.")
        
        module = Module.new(import_.module_name.format)
        checker = Checker.new(module)

        tokens = tuple(Lexer(Source(open(filepath).read()), module.name).lex())
        asts = tuple(Parser(Source(tokens), module.name).parse())

        for _ in checker.check(asts):
            continue

        self.module.imports[import_.module_name.rightest] = module

        return import_

    def check_struct_declaration(self, struct_declaration: StructDeclaration):
        # If struct is generic we dont perform checking just store it
        if struct_declaration.generic:
            generic_struct_type = GenericType(struct_declaration.name, struct_declaration.generic, struct_declaration, self.module)
            self.module.types[generic_struct_type.name] = generic_struct_type

            return generic_struct_type
        
        struct_declaration.fields = [(field_name, self.module.import_type(field_hint)) for field_name, field_hint in struct_declaration.fields]
        
        struct_type = Type(struct_declaration.name, struct_declaration.fields, dict(), struct_declaration, self.module.name)
        self.module.types[struct_type.name] = struct_type

        return struct_type
    
    def check_extern(self, extern: Extern):
        if type(extern.head) is not FunctionHead:
            raise NotImplementedError(f"checker(bug): checking for '{extern.format}' is not implemented yet")
        
        extern.head.parameters = [(parameter_name, self.module.import_type(parameter_hint)) for parameter_name, parameter_hint in extern.head.parameters]
        extern.head.return_hint = self.module.import_type(extern.head.return_hint)

        function = Function(extern)
        self.module.functions[extern.head.name] = function

        return extern

    def check_function_declaration(self, function_declaration: FunctionDeclaration):
        # If function is generic, ignore for now
        if function_declaration.head.generic:
            return function_declaration

        function_declaration.head.parameters = [(parameter_name, self.module.import_type(parameter_hint)) for parameter_name, parameter_hint in function_declaration.head.parameters]
        function_declaration.head.return_hint = self.module.import_type(function_declaration.head.return_hint)
        
        # Check and assign the associated function
        if type(function_declaration.head.name) is Attribute:
            associated_type = self.module.import_type(function_declaration.head.name.left)
            associated_function = AssociatedFunction(associated_type, function_declaration)
            associated_type.functions[function_declaration.head.name.right] = associated_function

            return associated_function

        # Now check its body
        checker = Checker(self.module, self.context.copy())
        function_declaration.body = checker.check_body(function_declaration.body)
        
        function = Function(function_declaration)
        self.module.functions[function_declaration.head.name] = function

        return function

    def check(self, asts: Ast):
        for ast in asts:
            if type(ast) is Import:
                yield self.check_import(ast)
            elif type(ast) is StructDeclaration:
                yield self.check_struct_declaration(ast)
            elif type(ast) is Extern:
                yield self.check_extern(ast)
            elif type(ast) is FunctionDeclaration:
                yield self.check_function_declaration(ast)
            else:
                raise NotImplementedError(f"bug(checker): checking for {ast.format} is not implemented yet. at line {ast.line}, in module {self.module.name}")

        return
    
    @classmethod
    def new(cls, module: Module):
        return cls(module, Context(module, module.imports, module.functions))