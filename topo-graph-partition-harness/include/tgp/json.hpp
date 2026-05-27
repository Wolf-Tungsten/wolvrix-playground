#ifndef TGP_JSON_HPP
#define TGP_JSON_HPP

#include <cstdint>
#include <map>
#include <string>
#include <variant>
#include <vector>

namespace tgp::json
{
    struct Value
    {
        using Array = std::vector<Value>;
        using Object = std::map<std::string, Value>;
        using Storage = std::variant<std::nullptr_t, bool, int64_t, double, std::string, Array, Object>;

        Storage storage;

        bool isObject() const noexcept;
        bool isArray() const noexcept;
        bool isString() const noexcept;
        bool isInt() const noexcept;
        bool isBool() const noexcept;

        const Object &object() const;
        const Array &array() const;
        const std::string &string() const;
        int64_t integer() const;
        bool boolean() const;
    };

    Value parse(std::string_view text);
    std::string escape(std::string_view text);

    const Value *find(const Value::Object &object, std::string_view key);
    const Value &require(const Value::Object &object, std::string_view key);
}

#endif
