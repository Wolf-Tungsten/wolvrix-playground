#include "tgp/json.hpp"

#include <cctype>
#include <cstdlib>
#include <stdexcept>
#include <string_view>

namespace tgp::json
{
    bool Value::isObject() const noexcept { return std::holds_alternative<Object>(storage); }
    bool Value::isArray() const noexcept { return std::holds_alternative<Array>(storage); }
    bool Value::isString() const noexcept { return std::holds_alternative<std::string>(storage); }
    bool Value::isInt() const noexcept { return std::holds_alternative<int64_t>(storage); }
    bool Value::isBool() const noexcept { return std::holds_alternative<bool>(storage); }

    const Value::Object &Value::object() const { return std::get<Object>(storage); }
    const Value::Array &Value::array() const { return std::get<Array>(storage); }
    const std::string &Value::string() const { return std::get<std::string>(storage); }
    int64_t Value::integer() const { return std::get<int64_t>(storage); }
    bool Value::boolean() const { return std::get<bool>(storage); }

    namespace
    {
        class Parser
        {
        public:
            explicit Parser(std::string_view text) : text_(text) {}

            Value parse()
            {
                Value value = parseValue();
                skipWs();
                if (pos_ != text_.size())
                {
                    throw std::runtime_error("trailing characters after JSON");
                }
                return value;
            }

        private:
            Value parseValue()
            {
                skipWs();
                if (pos_ >= text_.size())
                {
                    throw std::runtime_error("unexpected end of JSON");
                }
                const char ch = text_[pos_];
                if (ch == '{')
                {
                    return Value{parseObject()};
                }
                if (ch == '[')
                {
                    return Value{parseArray()};
                }
                if (ch == '"')
                {
                    return Value{parseString()};
                }
                if (ch == '-' || std::isdigit(static_cast<unsigned char>(ch)))
                {
                    return parseNumber();
                }
                if (consume("true"))
                {
                    return Value{true};
                }
                if (consume("false"))
                {
                    return Value{false};
                }
                if (consume("null"))
                {
                    return Value{nullptr};
                }
                throw std::runtime_error("invalid JSON value");
            }

            Value::Object parseObject()
            {
                expect('{');
                Value::Object object;
                skipWs();
                if (peek('}'))
                {
                    ++pos_;
                    return object;
                }
                while (true)
                {
                    skipWs();
                    if (!peek('"'))
                    {
                        throw std::runtime_error("JSON object key must be a string");
                    }
                    std::string key = parseString();
                    skipWs();
                    expect(':');
                    object.emplace(std::move(key), parseValue());
                    skipWs();
                    if (peek('}'))
                    {
                        ++pos_;
                        break;
                    }
                    expect(',');
                }
                return object;
            }

            Value::Array parseArray()
            {
                expect('[');
                Value::Array array;
                skipWs();
                if (peek(']'))
                {
                    ++pos_;
                    return array;
                }
                while (true)
                {
                    array.push_back(parseValue());
                    skipWs();
                    if (peek(']'))
                    {
                        ++pos_;
                        break;
                    }
                    expect(',');
                }
                return array;
            }

            std::string parseString()
            {
                expect('"');
                std::string out;
                while (pos_ < text_.size())
                {
                    const char ch = text_[pos_++];
                    if (ch == '"')
                    {
                        return out;
                    }
                    if (ch != '\\')
                    {
                        out.push_back(ch);
                        continue;
                    }
                    if (pos_ >= text_.size())
                    {
                        throw std::runtime_error("unterminated JSON escape");
                    }
                    const char esc = text_[pos_++];
                    switch (esc)
                    {
                    case '"': out.push_back('"'); break;
                    case '\\': out.push_back('\\'); break;
                    case '/': out.push_back('/'); break;
                    case 'b': out.push_back('\b'); break;
                    case 'f': out.push_back('\f'); break;
                    case 'n': out.push_back('\n'); break;
                    case 'r': out.push_back('\r'); break;
                    case 't': out.push_back('\t'); break;
                    case 'u':
                        if (pos_ + 4 > text_.size())
                        {
                            throw std::runtime_error("short JSON unicode escape");
                        }
                        // This harness protocol only needs ASCII keys/values. Preserve non-ASCII escapes as '?'.
                        pos_ += 4;
                        out.push_back('?');
                        break;
                    default:
                        throw std::runtime_error("invalid JSON escape");
                    }
                }
                throw std::runtime_error("unterminated JSON string");
            }

            Value parseNumber()
            {
                const std::size_t begin = pos_;
                if (peek('-'))
                {
                    ++pos_;
                }
                while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_])))
                {
                    ++pos_;
                }
                bool floating = false;
                if (pos_ < text_.size() && text_[pos_] == '.')
                {
                    floating = true;
                    ++pos_;
                    while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_])))
                    {
                        ++pos_;
                    }
                }
                if (pos_ < text_.size() && (text_[pos_] == 'e' || text_[pos_] == 'E'))
                {
                    floating = true;
                    ++pos_;
                    if (pos_ < text_.size() && (text_[pos_] == '+' || text_[pos_] == '-'))
                    {
                        ++pos_;
                    }
                    while (pos_ < text_.size() && std::isdigit(static_cast<unsigned char>(text_[pos_])))
                    {
                        ++pos_;
                    }
                }
                const std::string text(text_.substr(begin, pos_ - begin));
                if (floating)
                {
                    return Value{std::strtod(text.c_str(), nullptr)};
                }
                return Value{static_cast<int64_t>(std::strtoll(text.c_str(), nullptr, 10))};
            }

            void skipWs()
            {
                while (pos_ < text_.size() && std::isspace(static_cast<unsigned char>(text_[pos_])))
                {
                    ++pos_;
                }
            }

            bool consume(std::string_view literal)
            {
                if (text_.substr(pos_, literal.size()) != literal)
                {
                    return false;
                }
                pos_ += literal.size();
                return true;
            }

            bool peek(char ch) const
            {
                return pos_ < text_.size() && text_[pos_] == ch;
            }

            void expect(char ch)
            {
                if (!peek(ch))
                {
                    throw std::runtime_error("unexpected JSON character");
                }
                ++pos_;
            }

            std::string_view text_;
            std::size_t pos_ = 0;
        };
    }

    Value parse(std::string_view text)
    {
        return Parser(text).parse();
    }

    std::string escape(std::string_view text)
    {
        std::string out;
        out.reserve(text.size() + 8);
        for (const char ch : text)
        {
            switch (ch)
            {
            case '"': out += "\\\""; break;
            case '\\': out += "\\\\"; break;
            case '\n': out += "\\n"; break;
            case '\r': out += "\\r"; break;
            case '\t': out += "\\t"; break;
            default: out.push_back(ch); break;
            }
        }
        return out;
    }

    const Value *find(const Value::Object &object, std::string_view key)
    {
        const auto it = object.find(std::string(key));
        if (it == object.end())
        {
            return nullptr;
        }
        return &it->second;
    }

    const Value &require(const Value::Object &object, std::string_view key)
    {
        const Value *value = find(object, key);
        if (value == nullptr)
        {
            throw std::runtime_error("missing JSON key: " + std::string(key));
        }
        return *value;
    }
}
